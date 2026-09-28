"""Login sessions of the web UI (cookie-based, for our own `/api`)."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppUser, WebSession

REMEMBER_FOR = timedelta(days=30)
SESSION_FOR = timedelta(hours=12)  # without "remember me"
# Avoid a database write on every request: last_seen_at is refreshed at most this often.
TOUCH_EVERY = timedelta(minutes=5)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create(session: AsyncSession, user: AppUser, *, remember: bool) -> tuple[str, datetime]:
    """Opens a session. Returns the cookie value (never stored) and its expiry."""
    now = datetime.now(UTC)
    expires_at = now + (REMEMBER_FOR if remember else SESSION_FOR)
    token = secrets.token_urlsafe(32)
    session.add(WebSession(user_id=user.id, token_hash=_hash(token), expires_at=expires_at))
    # Opportunistic cleanup of expired sessions.
    await session.execute(delete(WebSession).where(WebSession.expires_at < now))
    await session.flush()
    return token, expires_at


async def resolve(session: AsyncSession, token: str) -> tuple[WebSession, AppUser] | None:
    now = datetime.now(UTC)
    row = (
        await session.execute(
            select(WebSession, AppUser)
            .join(AppUser, AppUser.id == WebSession.user_id)
            .where(WebSession.token_hash == _hash(token), WebSession.expires_at > now)
        )
    ).first()
    if row is None:
        return None
    web_session, user = row
    if now - web_session.last_seen_at > TOUCH_EVERY:
        web_session.last_seen_at = now
    return web_session, user


async def close(session: AsyncSession, session_id: uuid.UUID) -> None:
    await session.execute(delete(WebSession).where(WebSession.id == session_id))
