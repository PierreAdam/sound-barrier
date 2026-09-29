"""The Sound-Barrier server's worker API (`/api/transcriber`, see the server's
app/api/transcripts.py). Only outgoing HTTPS calls: the server never connects to this PC."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from sb_transcriber.config import Config

API_VERSION = 1  # the server's WORKER_API_VERSION this app speaks
RETRIES = 4
PART_LINES = 1000  # lines per upload (reverse proxies limit the size of a request)


class ServerError(Exception):
    pass


class LostClaimError(ServerError):
    """The file is no longer ours (the claim ran out, or an admin removed it)."""


@dataclass
class Claim:
    song_id: str
    album_id: str
    kind: str
    book: str
    author: str
    title: str
    file_name: str
    suffix: str
    size: int
    duration_ms: int
    lease_seconds: int


class Client:
    def __init__(self, config: Config) -> None:
        self._http = httpx.Client(
            base_url=f"{config.server}/api/transcriber",
            headers={"Authorization": f"Bearer {config.token}"},
            timeout=httpx.Timeout(60.0, connect=15.0),
            follow_redirects=True,
        )

    def close(self) -> None:
        self._http.close()

    def _call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """With retries on network errors and server restarts (a deploy)."""
        for attempt in range(RETRIES):
            try:
                response = self._http.request(method, path, **kwargs)
            except httpx.TransportError as error:
                if attempt == RETRIES - 1:
                    raise ServerError(f"Cannot reach the server: {error}") from error
            else:
                if response.status_code not in (502, 503, 504) or attempt == RETRIES - 1:
                    return self._check(response)
            time.sleep(2 * 2**attempt)
        raise AssertionError("unreachable")

    @staticmethod
    def _check(response: httpx.Response) -> httpx.Response:
        if response.status_code == 409:
            raise LostClaimError(_detail(response))
        if response.status_code == 401:
            raise ServerError(
                "The server refused the token (revoked?): run `transcriber login` again"
            )
        if response.status_code == 413:
            raise ServerError(
                "The server (its reverse proxy) refused a request as too large: "
                "raise its body size limit (nginx: client_max_body_size)"
            )
        if response.is_error:
            raise ServerError(f"HTTP {response.status_code}: {_detail(response)}")
        return response

    # --- calls ---

    def hello(self) -> dict[str, Any]:
        found: dict[str, Any] = self._call("GET", "/hello").json()
        if found.get("apiVersion") != API_VERSION:
            raise ServerError(
                f"This app speaks version {API_VERSION} of the worker API, the server "
                f"{found.get('apiVersion')}: update Sound-Barrier or this app"
            )
        return found

    def books(self, kind: str | None = None) -> list[dict[str, Any]]:
        params = {"kind": kind} if kind else None
        return self._call("GET", "/books", params=params).json()

    def book(self, album_id: str) -> dict[str, Any]:
        return self._call("GET", f"/books/{album_id}").json()

    def claim(
        self,
        *,
        album_id: str | None = None,
        kind: str | None = None,
        retry_failed: bool = False,
        instance: str | None = None,
    ) -> Claim | None:
        body = {
            "albumId": album_id,
            "kind": kind,
            "retryFailed": retry_failed,
            "instance": instance,
        }
        response = self._call("POST", "/claim", json=body)
        if response.status_code == 204:
            return None
        data = response.json()
        return Claim(
            song_id=data["songId"],
            album_id=data["albumId"],
            kind=data["kind"],
            book=data["book"],
            author=data["author"],
            title=data["title"],
            file_name=data["fileName"],
            suffix=data["suffix"],
            size=data["size"],
            duration_ms=data["durationMs"],
            lease_seconds=data["leaseSeconds"],
        )

    def download(self, claim: Claim, target: Path, on_progress: Callable[[int], None]) -> None:
        """The audio file, into `target`; `on_progress(bytes so far)` renews the claim."""
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        try:
            with self._http.stream(
                "GET", f"/files/{claim.song_id}/audio", timeout=httpx.Timeout(120.0)
            ) as response:
                self._check(response)
                received = 0
                with partial.open("wb") as file:
                    for chunk in response.iter_bytes(1 << 20):
                        file.write(chunk)
                        received += len(chunk)
                        on_progress(received)
            partial.replace(target)
        except httpx.TransportError as error:
            raise ServerError(f"Download interrupted: {error}") from error
        finally:
            partial.unlink(missing_ok=True)

    def progress(self, song_id: str, progress: float | None = None) -> None:
        self._call("POST", f"/files/{song_id}/progress", json={"progress": progress})

    def release(self, song_id: str) -> None:
        self._call("POST", f"/files/{song_id}/release")

    def fail(self, song_id: str, error: str) -> None:
        self._call("POST", f"/files/{song_id}/fail", json={"error": error[:10_000]})

    def upload(
        self, song_id: str, model: str, language: str | None, lines: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """The transcript, in parts of PART_LINES lines."""
        parts = [lines[i : i + PART_LINES] for i in range(0, len(lines), PART_LINES)] or [[]]
        answer: dict[str, Any] = {}
        for index, part in enumerate(parts):
            body = {
                "model": model,
                "language": language,
                "lines": part,
                "part": index,
                "last": index == len(parts) - 1,
            }
            answer = self._call("PUT", f"/files/{song_id}/transcript", json=body).json()
        return answer


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    return str(detail) if detail else response.text[:300] or response.reason_phrase
