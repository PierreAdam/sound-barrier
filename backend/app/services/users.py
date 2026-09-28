"""Users and roles.

Sound-Barrier has two roles: **admin** (every right) and **user** (listen, download,
playlists, own password). Subsonic has many role flags; they are derived from the role.
"""

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import PasswordCipher, generate_api_key, hash_api_key
from app.models import ApiKey, AppUser, WebSession

logger = logging.getLogger(__name__)

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin"


class UserError(Exception):
    """A user operation that is not allowed; the message is shown to the admin."""


class UserAlreadyExistsError(UserError):
    pass


def apply_role(user: AppUser, *, admin: bool) -> None:
    """Sets the Subsonic role flags matching one of our two roles."""
    user.is_admin = admin
    user.settings_role = True  # change own password
    user.stream_role = True
    user.download_role = True
    user.playlist_role = True
    user.cover_art_role = True
    user.comment_role = True
    user.upload_role = admin
    user.podcast_role = admin
    user.jukebox_role = admin
    user.share_role = admin
    user.video_conversion_role = admin


async def ensure_default_admin(session: AsyncSession, cipher: PasswordCipher) -> None:
    """Creates admin/admin when there is no user at all (first start).

    Only an empty user table triggers it, so deleting or renaming the admin later does not
    bring it back. Warns on every start while the default password is still in use.
    """
    if not await session.scalar(select(exists().select_from(AppUser))):
        # ON CONFLICT: several server workers may start at the same time.
        await session.execute(
            insert(AppUser)
            .values(
                username=DEFAULT_ADMIN_USERNAME,
                password_enc=cipher.encrypt(DEFAULT_ADMIN_PASSWORD),
                is_admin=True,
            )
            .on_conflict_do_nothing(index_elements=[AppUser.username])
        )
        logger.warning(
            "Created the default user %r with password %r",
            DEFAULT_ADMIN_USERNAME,
            DEFAULT_ADMIN_PASSWORD,
        )
    admin = await get_by_username(session, DEFAULT_ADMIN_USERNAME)
    if admin is not None and cipher.decrypt(admin.password_enc) == DEFAULT_ADMIN_PASSWORD:
        logger.warning(
            "User %r still has the default password. Change it in Settings or with: "
            "sound-barrier set-password %s",
            DEFAULT_ADMIN_USERNAME,
            DEFAULT_ADMIN_USERNAME,
        )


async def list_users(session: AsyncSession) -> Sequence[AppUser]:
    return (await session.scalars(select(AppUser).order_by(func.lower(AppUser.username)))).all()


async def get_by_username(session: AsyncSession, username: str) -> AppUser | None:
    return await session.scalar(select(AppUser).where(AppUser.username == username))


async def get_by_api_key(session: AsyncSession, key: str) -> AppUser | None:
    api_key = await session.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(key)))
    if api_key is None:
        return None
    api_key.last_used_at = datetime.now(UTC)
    return await session.get(AppUser, api_key.user_id)


def _validate(username: str, password: str | None) -> None:
    if not username.strip() or username != username.strip():
        raise UserError("The username cannot be empty or start / end with spaces")
    if password is not None and not password:
        raise UserError("The password cannot be empty")


async def create_user(
    session: AsyncSession,
    cipher: PasswordCipher,
    username: str,
    password: str,
    *,
    email: str | None = None,
    is_admin: bool = False,
) -> AppUser:
    _validate(username, password)
    if await get_by_username(session, username) is not None:
        raise UserAlreadyExistsError(f"User {username} already exists")
    user = AppUser(username=username, password_enc=cipher.encrypt(password), email=email)
    apply_role(user, admin=is_admin)
    session.add(user)
    await session.flush()
    return user


async def _admin_count(session: AsyncSession) -> int:
    return (
        await session.scalar(select(func.count()).select_from(AppUser).where(AppUser.is_admin)) or 0
    )


async def set_role(session: AsyncSession, actor: AppUser, user: AppUser, *, admin: bool) -> None:
    if user.is_admin and not admin:
        if user.id == actor.id:
            raise UserError("You cannot remove your own admin role")
        if await _admin_count(session) <= 1:
            raise UserError("At least one admin is required")
    apply_role(user, admin=admin)


async def delete_user(session: AsyncSession, actor: AppUser, user: AppUser) -> None:
    if user.id == actor.id:
        raise UserError("You cannot delete your own account")
    if user.is_admin and await _admin_count(session) <= 1:
        raise UserError("At least one admin is required")
    await session.delete(user)
    await session.flush()


async def set_password(
    session: AsyncSession,
    user: AppUser,
    cipher: PasswordCipher,
    password: str,
    *,
    keep_session_id: uuid.UUID | None = None,
) -> None:
    """Changes the password and signs the user out of their other web sessions."""
    _validate(user.username, password)
    user.password_enc = cipher.encrypt(password)
    statement = delete(WebSession).where(WebSession.user_id == user.id)
    if keep_session_id is not None:
        statement = statement.where(WebSession.id != keep_session_id)
    await session.execute(statement)


async def create_api_key(session: AsyncSession, user: AppUser, name: str) -> str:
    """Returns the new key. Only its hash is stored, so it cannot be shown again."""
    key = generate_api_key()
    session.add(ApiKey(user_id=user.id, name=name, key_hash=hash_api_key(key)))
    await session.flush()
    return key
