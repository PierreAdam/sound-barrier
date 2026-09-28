"""Serves the built web UI (single-page app) next to the APIs, on the same origin."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse

# Paths owned by the APIs: an unknown one is a 404, never the web page.
_API_PREFIXES = ("rest/", "api/")


def mount_web(app: FastAPI, web_dir: Path) -> None:
    """Static files of `web_dir`; any other path gets index.html (client-side routes)."""
    root = web_dir.resolve()
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError(f"No index.html in the web directory: {root}")

    # Synchronous: FastAPI runs it in a thread (file-system checks).
    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def web(path: str) -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        if path.startswith(_API_PREFIXES) or path in ("rest", "api"):
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        file = (root / path).resolve()
        if path and file.is_relative_to(root) and file.is_file():
            # Vite puts a content hash in asset names: they never change.
            cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else None
            return FileResponse(file, headers={"Cache-Control": cache} if cache else None)
        # index.html must always be revalidated, it names the current assets.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
