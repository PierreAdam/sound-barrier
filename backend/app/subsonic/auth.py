"""Subsonic authentication: `apiKey`, `u` + `t` + `s` (token), or `u` + `p` (password)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import PasswordCipher, constant_time_equals, subsonic_token
from app.models import AppUser
from app.services import users
from app.subsonic.errors import ErrorCode, SubsonicError
from app.subsonic.params import SubsonicParams


def _wrong_credentials() -> SubsonicError:
    return SubsonicError(ErrorCode.WRONG_CREDENTIALS, "Wrong username or password")


def decode_password_param(p: str) -> str:
    """`p` is either plaintext or `enc:` followed by the hex-encoded password."""
    if p.startswith("enc:"):
        try:
            return bytes.fromhex(p[4:]).decode()
        except ValueError:
            raise _wrong_credentials() from None
    return p


def check_password(password: str, params: SubsonicParams) -> bool:
    """Checks the request credentials (token or password) against the user's password."""
    token, salt = params.get("t"), params.get("s")
    if token and salt:
        return constant_time_equals(subsonic_token(password, salt), token.lower())
    p = params.get("p")
    if p:
        return constant_time_equals(password, decode_password_param(p))
    raise SubsonicError.missing("p or t and s")


async def authenticate(
    session: AsyncSession, cipher: PasswordCipher, params: SubsonicParams
) -> AppUser:
    api_key = params.get("apiKey")
    if api_key is not None:
        if "u" in params:
            raise SubsonicError(
                ErrorCode.MULTIPLE_AUTH_MECHANISMS, "Provide either apiKey or u, not both"
            )
        user = await users.get_by_api_key(session, api_key)
        if user is None:
            raise SubsonicError(ErrorCode.INVALID_API_KEY, "Invalid API key")
        return user

    username = params.require("u")
    user = await users.get_by_username(session, username)
    if user is None:
        # Still run the check so an unknown user looks the same as a wrong password.
        check_password("", params)
        raise _wrong_credentials()
    if not check_password(cipher.decrypt(user.password_enc), params):
        raise _wrong_credentials()
    return user
