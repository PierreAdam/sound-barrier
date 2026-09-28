import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from testcontainers.community.postgres import PostgresContainer

from app.core.config import Settings
from app.core.crypto import PasswordCipher, generate_secret_key
from app.core.db import Database
from app.main import create_app
from app.services import music_folders, users

BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer("postgres:16", driver="asyncpg") as postgres:
        url = postgres.get_connection_url()
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", url)
        config.attributes["configure_logger"] = False
        command.upgrade(config, "head")
        yield url


@pytest.fixture(scope="session")
def settings(database_url: str, tmp_path_factory: pytest.TempPathFactory) -> Settings:
    return Settings(
        database_url=database_url,
        secret_key=SecretStr(generate_secret_key()),
        data_dir=tmp_path_factory.mktemp("data"),
        scheduler=False,
        tagger="as-is",  # no MusicBrainz lookups (beets: tests/unit/test_beets_tagger.py)
        # Many tests use wrong passwords, all from the same address: throttling has its own
        # test (test_throttle.py).
        login_max_failures=100_000,
    )


@pytest.fixture(scope="session")
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture(scope="session")
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
def db(app: FastAPI) -> Database:
    return app.state.db


@dataclass
class SubsonicUser:
    username: str
    password: str

    def params(self, **extra: str) -> dict[str, str]:
        """Common Subsonic params with plain password auth, JSON format."""
        return {
            "u": self.username,
            "p": self.password,
            "v": "1.16.1",
            "c": "tests",
            "f": "json",
            **extra,
        }


async def _create_user(app: FastAPI, *, is_admin: bool) -> SubsonicUser:
    cipher: PasswordCipher = app.state.cipher
    user = SubsonicUser(username=f"user-{uuid.uuid4().hex[:8]}", password=uuid.uuid4().hex)
    async with app.state.db.session() as session:
        await users.create_user(session, cipher, user.username, user.password, is_admin=is_admin)
        await session.commit()
    return user


@pytest.fixture
async def user(app: FastAPI) -> SubsonicUser:
    return await _create_user(app, is_admin=False)


@pytest.fixture
async def admin(app: FastAPI) -> SubsonicUser:
    return await _create_user(app, is_admin=True)


LIBRARY_TABLES = "music_folder, artist, album, genre, artwork, directory, song, scan"


@pytest.fixture
async def library(db: Database, tmp_path: Path) -> Path:
    """An empty music folder, the only one in the database."""
    root = tmp_path / "music"
    root.mkdir()
    async with db.session() as session:
        await session.execute(text(f"TRUNCATE {LIBRARY_TABLES} CASCADE"))
        await music_folders.create(session, "Music", root)
        await session.commit()
    return root


@asynccontextmanager
async def signed_in(
    app: FastAPI, user: SubsonicUser, remember: bool = False
) -> AsyncIterator[AsyncClient]:
    """A separate client (own cookie jar) signed in to /api."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/auth/login",
            json={"username": user.username, "password": user.password, "remember": remember},
        )
        assert response.status_code == 200, response.text
        yield client
