import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.db import Database
from app.scanner.scanner import run_scan
from tests.audio import album_tracks
from tests.integration.conftest import SubsonicUser, signed_in

pytestmark = pytest.mark.integration


async def test_login_me_logout(app: FastAPI, admin: SubsonicUser) -> None:
    async with signed_in(app, admin) as client:
        cookie = client.cookies.jar
        assert any(c.name == "sb_session" for c in cookie)
        me = (await client.get("/api/auth/me")).json()
        assert me == {"username": admin.username, "admin": True}
        assert (await client.post("/api/auth/logout")).status_code == 204
        assert (await client.get("/api/auth/me")).status_code == 401


async def test_login_errors_and_anonymous_access(client: AsyncClient, user: SubsonicUser) -> None:
    response = await client.post(
        "/api/auth/login", json={"username": user.username, "password": "wrong"}
    )
    assert response.status_code == 401
    response = await client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    assert response.status_code == 401
    for path in ("/api/auth/me", "/api/library", "/api/scan", "/api/scan/schedule"):
        assert (await client.get(path)).status_code == 401, path


async def test_admin_only_routes(app: FastAPI, user: SubsonicUser) -> None:
    async with signed_in(app, user) as client:
        assert (await client.get("/api/auth/me")).json()["admin"] is False
        for path in ("/api/library", "/api/scan", "/api/scan/schedule"):
            assert (await client.get(path)).status_code == 403, path


async def test_change_own_password_keeps_this_session(app: FastAPI, user: SubsonicUser) -> None:
    async with signed_in(app, user) as other, signed_in(app, user) as client:
        response = await client.put("/api/auth/password", json={"password": "changed"})
        assert response.status_code == 204
        assert (await client.get("/api/auth/me")).status_code == 200  # still signed in
        assert (await other.get("/api/auth/me")).status_code == 401  # other session closed
        ping = await client.get("/rest/ping", params={**user.params(), "p": "changed"})
        assert ping.json()["subsonic-response"]["status"] == "ok"
        response = await client.put("/api/auth/password", json={"password": ""})
        assert response.status_code == 400


async def test_library_folder(
    app: FastAPI, admin: SubsonicUser, library: Path, tmp_path: Path
) -> None:
    async with signed_in(app, admin) as client:
        folder = (await client.get("/api/library")).json()["folder"]
        assert folder["reachable"] is True
        assert Path(folder["path"]) == library

        response = await client.put("/api/library", json={"path": str(tmp_path / "nope")})
        assert response.status_code == 400
        assert "Not a directory" in response.json()["detail"]

        moved = tmp_path / "moved"
        moved.mkdir()
        response = await client.put("/api/library", json={"path": str(moved), "name": "Main"})
        updated = response.json()["folder"]
        assert (updated["id"], updated["name"], Path(updated["path"])) == (
            folder["id"],
            "Main",
            moved,
        )
        await wait_for_scan(client)


async def wait_for_scan(client: AsyncClient) -> dict[str, Any]:
    for _ in range(100):
        status = (await client.get("/api/scan")).json()
        if not status["running"]:
            return status
        await asyncio.sleep(0.05)
    raise AssertionError("scan did not finish")


async def test_scan_progress(app: FastAPI, admin: SubsonicUser, library: Path) -> None:
    album_tracks(library, "Artist", "Album", 3)
    async with signed_in(app, admin) as client:
        response = await client.post("/api/scan", json={"full": True})
        assert response.status_code == 202
        assert response.json()["running"] is True
        status = await wait_for_scan(client)
        latest = status["latest"]
        assert (latest["status"], latest["phase"], latest["kind"]) == ("done", "done", "full")
        assert (latest["filesSeen"], latest["filesToRead"], latest["filesRead"]) == (3, 3, 3)
        assert latest["added"] == 3
        assert status["songCount"] == 3


async def test_schedule(app: FastAPI, admin: SubsonicUser) -> None:
    async with signed_in(app, admin) as client:
        schedule = (await client.get("/api/scan/schedule")).json()
        assert (schedule["enabled"], schedule["time"], schedule["scanOnStartup"]) == (
            True,
            "02:00",
            True,
        )
        assert schedule["nextRunAt"] is not None
        assert schedule["timeZone"]

        body = {"enabled": True, "time": "04:30", "scanOnStartup": False}
        saved = (await client.put("/api/scan/schedule", json=body)).json()
        assert (saved["time"], saved["scanOnStartup"]) == ("04:30", False)
        assert "T04:30:00" in saved["nextRunAt"]
        assert (await client.get("/api/scan/schedule")).json()["time"] == "04:30"

        off = (await client.put("/api/scan/schedule", json={**body, "enabled": False})).json()
        assert off["nextRunAt"] is None

        bad = await client.put("/api/scan/schedule", json={**body, "time": "25:00"})
        assert bad.status_code == 400
        await client.put(
            "/api/scan/schedule", json={**body, "time": "02:00", "scanOnStartup": True}
        )


async def test_library_revision_changes_after_a_scan(
    app: FastAPI, user: SubsonicUser, library: Path, db: Database
) -> None:
    async with signed_in(app, user) as client:  # any signed-in user, not only admins
        before = (await client.get("/api/library/revision")).json()["revision"]
        album_tracks(library, "Band", "Album", 1)
        await run_scan(db)
        after = (await client.get("/api/library/revision")).json()["revision"]
    assert after > before
