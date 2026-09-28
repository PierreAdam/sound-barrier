"""Dependencies of our own API: database session and the logged-in user (cookie)."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import PasswordCipher
from app.core.db import Database
from app.models import AppUser, WebSession
from app.services import web_sessions
from app.services.scans import ScanManager

SESSION_COOKIE = "sb_session"


class ApiModel(BaseModel):
    """JSON bodies use camelCase, like the Subsonic API the web UI also talks to."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


async def db_session(request: Request) -> AsyncIterator[AsyncSession]:
    db: Database = request.app.state.db
    async with db.session() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(db_session)]


@dataclass(frozen=True)
class Caller:
    user: AppUser
    web_session: WebSession


async def current_caller(request: Request, session: DbSession) -> Caller:
    token = request.cookies.get(SESSION_COOKIE)
    found = await web_sessions.resolve(session, token) if token else None
    if found is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    await session.commit()  # last_seen_at
    return Caller(user=found[1], web_session=found[0])


async def admin_caller(caller: Annotated[Caller, Depends(current_caller)]) -> Caller:
    if not caller.user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admins only")
    return caller


CurrentCaller = Annotated[Caller, Depends(current_caller)]
AdminCaller = Annotated[Caller, Depends(admin_caller)]


def cipher(request: Request) -> PasswordCipher:
    return request.app.state.cipher


def scan_manager(request: Request) -> ScanManager:
    return request.app.state.scans
