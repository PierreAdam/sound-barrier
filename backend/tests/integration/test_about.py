"""The About page: the server's libraries for everyone, its runtime for admins."""

import pytest
from fastapi import FastAPI

from tests.integration.conftest import SubsonicUser, signed_in

pytestmark = pytest.mark.integration


async def test_libraries_and_runtime(app: FastAPI, admin: SubsonicUser, user: SubsonicUser) -> None:
    async with signed_in(app, user) as web:
        about = (await web.get("/api/about")).json()
    libraries = {lib["name"].lower(): lib for lib in about["libraries"]}
    assert libraries["fastapi"]["direct"] is True
    assert libraries["starlette"]["direct"] is False  # needed by FastAPI
    assert libraries["fastapi"]["version"] and libraries["fastapi"]["license"]
    assert about["runtime"] is None  # not for every account

    async with signed_in(app, admin) as web:
        runtime = (await web.get("/api/about")).json()["runtime"]
    assert runtime["version"]
    assert runtime["python"].split()[0] in {"CPython", "PyPy"}
    assert runtime["postgres"].startswith("PostgreSQL ")
    assert runtime["uptimeS"] >= 0
