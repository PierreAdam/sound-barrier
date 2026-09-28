from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.web import mount_web


def _client(tmp_path: Path) -> AsyncClient:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>index</html>")
    (tmp_path / "assets" / "app-1234.js").write_text("js")
    (tmp_path / "favicon.ico").write_bytes(b"ico")
    (tmp_path.parent / "secret.txt").write_text("secret")
    app = FastAPI()

    @app.get("/api/known")
    def known() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"ok": "yes"}

    mount_web(app, tmp_path)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_serves_files_and_spa_routes(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert (await client.get("/favicon.ico")).content == b"ico"
    asset = await client.get("/assets/app-1234.js")
    assert asset.text == "js"
    assert "immutable" in asset.headers["cache-control"]
    for path in ("/", "/browse", "/artist/123", "/assets/missing.js"):
        response = await client.get(path)
        assert response.text == "<html>index</html>", path
        assert response.headers["cache-control"] == "no-cache"
    assert (await client.head("/")).status_code == 200


async def test_apis_are_not_shadowed(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert (await client.get("/api/known")).json() == {"ok": "yes"}
    for path in ("/api/unknown", "/rest/unknown", "/api"):
        assert (await client.get(path)).status_code == 404, path


async def test_no_file_outside_the_web_folder(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/%2e%2e/%2e%2e/secret.txt"):
        assert "secret" not in (await client.get(path)).text, path
