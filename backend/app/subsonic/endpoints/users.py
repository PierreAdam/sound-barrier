"""User management (Subsonic API): getUser(s), createUser, updateUser, deleteUser,
changePassword. Our two roles (admin / user) map to Subsonic's `adminRole`; the other
role flags are derived from it (see services.users.apply_role)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import PasswordCipher
from app.models import AppUser
from app.services import music_folders, users
from app.subsonic import schemas
from app.subsonic.auth import decode_password_param
from app.subsonic.envelope import Payload
from app.subsonic.errors import ErrorCode, SubsonicError
from app.subsonic.router import SubsonicContext, registry


async def to_schema(session: AsyncSession, user: AppUser) -> schemas.User:
    folders = await music_folders.list_for_user(session, user)
    return schemas.User(
        username=user.username,
        email=user.email,
        scrobbling_enabled=user.scrobbling_enabled,
        max_bit_rate=user.max_bit_rate,
        admin_role=user.is_admin,
        settings_role=user.settings_role,
        download_role=user.download_role,
        upload_role=user.upload_role,
        playlist_role=user.playlist_role,
        cover_art_role=user.cover_art_role,
        comment_role=user.comment_role,
        podcast_role=user.podcast_role,
        stream_role=user.stream_role,
        jukebox_role=user.jukebox_role,
        share_role=user.share_role,
        video_conversion_role=user.video_conversion_role,
        folder=[f.id for f in folders],
    )


def _require_admin(ctx: SubsonicContext) -> None:
    if not ctx.user.is_admin:
        raise SubsonicError.not_authorized("Only admins can manage users")


async def _target(ctx: SubsonicContext) -> AppUser:
    user = await users.get_by_username(ctx.session, ctx.params.require("username"))
    if user is None:
        raise SubsonicError.not_found("User")
    return user


def _cipher(ctx: SubsonicContext) -> PasswordCipher:
    return ctx.request.app.state.cipher


def _user_error(error: users.UserError) -> SubsonicError:
    return SubsonicError(ErrorCode.GENERIC, str(error))


@registry.endpoint("getUser")
async def get_user(ctx: SubsonicContext) -> Payload:
    username = ctx.params.require("username")
    if username != ctx.user.username and not ctx.user.is_admin:
        raise SubsonicError.not_authorized("Only admins can see other users")
    return {"user": await to_schema(ctx.session, await _target(ctx))}


@registry.endpoint("getUsers")
async def get_users(ctx: SubsonicContext) -> Payload:
    _require_admin(ctx)
    all_users = [await to_schema(ctx.session, u) for u in await users.list_users(ctx.session)]
    return {"users": schemas.Users(user=all_users)}


@registry.endpoint("createUser")
async def create_user(ctx: SubsonicContext) -> Payload:
    _require_admin(ctx)
    try:
        await users.create_user(
            ctx.session,
            _cipher(ctx),
            ctx.params.require("username"),
            decode_password_param(ctx.params.require("password")),
            email=ctx.params.get("email") or None,
            is_admin=ctx.params.get_bool("adminRole"),
        )
    except users.UserError as error:
        raise _user_error(error) from None
    return None


@registry.endpoint("updateUser")
async def update_user(ctx: SubsonicContext) -> Payload:
    _require_admin(ctx)
    user = await _target(ctx)
    try:
        if "adminRole" in ctx.params:
            await users.set_role(
                ctx.session, ctx.user, user, admin=ctx.params.get_bool("adminRole")
            )
        if "email" in ctx.params:
            user.email = ctx.params.get("email") or None
        password = ctx.params.get("password")
        if password:
            await users.set_password(
                ctx.session, user, _cipher(ctx), decode_password_param(password)
            )
    except users.UserError as error:
        raise _user_error(error) from None
    return None


@registry.endpoint("deleteUser")
async def delete_user(ctx: SubsonicContext) -> Payload:
    _require_admin(ctx)
    user = await _target(ctx)
    try:
        await users.delete_user(ctx.session, ctx.user, user)
    except users.UserError as error:
        raise _user_error(error) from None
    return None


@registry.endpoint("changePassword")
async def change_password(ctx: SubsonicContext) -> Payload:
    user = await _target(ctx)
    if user.id != ctx.user.id and not ctx.user.is_admin:
        raise SubsonicError.not_authorized("Only admins can change other users' passwords")
    try:
        await users.set_password(
            ctx.session, user, _cipher(ctx), decode_password_param(ctx.params.require("password"))
        )
    except users.UserError as error:
        raise _user_error(error) from None
    return None
