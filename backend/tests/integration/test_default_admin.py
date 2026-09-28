import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import delete, func, select

from app.core.db import Database
from app.models import AppUser
from app.services import users

pytestmark = pytest.mark.integration

ADMIN = {"u": "admin", "p": "admin", "v": "1.16.1", "c": "tests", "f": "json"}


async def test_default_admin_created_on_first_start(client: AsyncClient) -> None:
    data = (await client.get("/rest/getUser", params={**ADMIN, "username": "admin"})).json()
    user = data["subsonic-response"]["user"]
    assert user["username"] == "admin"
    assert user["adminRole"] is True


async def test_default_admin_not_recreated(app: FastAPI, db: Database) -> None:
    async with db.session() as session:
        await users.create_user(session, app.state.cipher, "someone-else", "secret")
        await session.execute(delete(AppUser).where(AppUser.username == "admin"))
        await session.commit()

        # Other users exist: deleting the admin must not bring it back on restart.
        await users.ensure_default_admin(session, app.state.cipher)
        await session.commit()
        count = await session.scalar(
            select(func.count()).select_from(AppUser).where(AppUser.username == "admin")
        )
    assert count == 0
