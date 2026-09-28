"""Sign in / out of our own API, and the caller's own password."""

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import SESSION_COOKIE, ApiModel, CurrentCaller, DbSession, cipher
from app.core.crypto import constant_time_equals
from app.core.throttle import LoginThrottle, client_address, minutes
from app.services import users, web_sessions

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(ApiModel):
    username: str
    password: str
    remember: bool = False


class Me(ApiModel):
    username: str
    admin: bool


class PasswordChange(ApiModel):
    password: str


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response, session: DbSession) -> Me:
    throttle: LoginThrottle = request.app.state.throttle
    address = client_address(request)
    blocked = throttle.blocked_for(address)
    if blocked:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many failed sign-ins: try again in {minutes(blocked)} minutes",
        )
    user = await users.get_by_username(session, body.username)
    valid = user is not None and constant_time_equals(
        cipher(request).decrypt(user.password_enc), body.password
    )
    if user is None or not valid:
        throttle.failure(address)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password")
    throttle.success(address)
    token, expires_at = await web_sessions.create(session, user, remember=body.remember)
    await session.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        # Without "remember me" the cookie lasts until the browser closes.
        expires=expires_at if body.remember else None,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/api",
    )
    return Me(username=user.username, admin=user.is_admin)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, session: DbSession) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    found = await web_sessions.resolve(session, token) if token else None
    if found is not None:
        await web_sessions.close(session, found[0].id)
        await session.commit()
    response.delete_cookie(SESSION_COOKIE, path="/api")


@router.get("/me")
async def me(caller: CurrentCaller) -> Me:
    return Me(username=caller.user.username, admin=caller.user.is_admin)


@router.put("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_own_password(
    body: PasswordChange, request: Request, caller: CurrentCaller, session: DbSession
) -> None:
    """Changes the caller's password; their other web sessions are signed out, this one
    stays open. (Subsonic's changePassword cannot tell which session is the caller's.)"""
    # `caller` was loaded in this same request session (FastAPI caches dependencies).
    try:
        await users.set_password(
            session,
            caller.user,
            cipher(request),
            body.password,
            keep_session_id=caller.web_session.id,
        )
    except users.UserError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from None
    await session.commit()
