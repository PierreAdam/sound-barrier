"""The About page: the libraries the server runs on, and its runtime (Python, operating
system, PostgreSQL, ffmpeg)."""

import asyncio
import os
import platform
import shutil
import sys
import time
import tomllib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import cache
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__

DISTRIBUTION = "sound-barrier"
STARTED_AT = datetime.now(UTC)
_started = time.monotonic()


@dataclass(frozen=True)
class Library:
    name: str
    version: str
    license: str | None
    summary: str | None
    url: str | None
    direct: bool  # declared by Sound-Barrier itself (else needed by another library)


@dataclass(frozen=True)
class Runtime:
    version: str  # Sound-Barrier
    python: str  # e.g. "CPython 3.13.7"
    os: str  # e.g. "Debian GNU/Linux 13 (trixie)"
    kernel: str  # e.g. "Linux 6.8.0-45-generic"
    architecture: str  # e.g. "x86_64"
    container: bool  # running in Docker
    cpus: int | None
    postgres: str | None
    ffmpeg: str | None
    time_zone: str
    started_at: datetime
    uptime_s: int


def _license(dist: metadata.Distribution) -> str | None:
    """The license, short: SPDX expression, else the License field when it is a name
    (not the whole license text), else the classifiers."""
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression
    field = (meta.get("License") or "").strip()
    if field and len(field) <= 60 and "\n" not in field and field.upper() != "UNKNOWN":
        return field
    classifiers = [
        c.split("::")[-1].strip()
        for c in meta.get_all("Classifier") or []
        if c.startswith("License ::") and c.count("::") >= 2
    ]
    return ", ".join(dict.fromkeys(classifiers)) or None


def _url(dist: metadata.Distribution) -> str | None:
    meta = dist.metadata
    urls = {
        label.strip().casefold(): link.strip()
        for entry in meta.get_all("Project-URL") or []
        if "," in entry
        for label, link in [entry.split(",", 1)]
    }
    for key in ("homepage", "home", "source", "source code", "repository", "documentation"):
        if key in urls:
            return urls[key]
    return meta.get("Home-page") or next(iter(urls.values()), None)


def _requirements(dist: metadata.Distribution, extras: set[str]) -> list[Requirement]:
    """What a library needs to run (its extras only when asked for, no test / dev ones)."""
    found: list[Requirement] = []
    for raw in dist.requires or []:
        requirement = Requirement(raw)
        marker = requirement.marker
        if marker is None or any(marker.evaluate({"extra": extra}) for extra in extras or {""}):
            found.append(requirement)
    return found


@cache
def _declared() -> list[Requirement]:
    """Sound-Barrier's own dependencies: pyproject.toml next to the `app` package (the
    sources, and the Docker image's /app), else the installed metadata."""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if pyproject.is_file():
        project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
        return [Requirement(raw) for raw in project.get("dependencies", [])]
    try:
        return _requirements(metadata.distribution(DISTRIBUTION), set())
    except metadata.PackageNotFoundError:
        return []


@cache
def libraries() -> list[Library]:
    """Every library the server runs on: Sound-Barrier's dependencies and theirs, as
    installed (never the development tools), by name."""
    declared = _declared()
    direct = {canonicalize_name(r.name) for r in declared}
    seen: dict[str, Library] = {}
    followed: dict[str, set[str]] = {}  # the extras whose requirements were followed
    queue = list(declared)
    while queue:
        requirement = queue.pop()
        key = canonicalize_name(requirement.name)
        extras = set(requirement.extras)
        done = followed.get(key)
        if done is not None and extras <= done:
            continue  # already followed with these extras
        try:
            dist = metadata.distribution(requirement.name)
        except metadata.PackageNotFoundError:
            continue  # optional, not installed here (e.g. another platform's)
        if key not in seen:
            seen[key] = Library(
                name=dist.metadata["Name"] or requirement.name,
                version=dist.version,
                license=_license(dist),
                summary=dist.metadata.get("Summary"),
                url=_url(dist),
                direct=key in direct,
            )
        # Reached again with more extras (e.g. uvicorn[standard]): follow them too (what
        # was already followed is skipped above).
        followed[key] = (done or set()) | extras
        queue += _requirements(dist, followed[key])
    return sorted(seen.values(), key=lambda lib: lib.name.casefold())


def _os_name() -> str:
    """The distribution's name (/etc/os-release: e.g. the Docker image's Debian), else
    the platform's."""
    try:
        return platform.freedesktop_os_release().get("PRETTY_NAME") or platform.platform()
    except OSError:
        pass
    if sys.platform == "win32":
        return f"Windows {platform.release()} ({platform.version()})"
    if sys.platform == "darwin":
        return f"macOS {platform.mac_ver()[0]}"
    return platform.platform()


@cache
def _ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


_ffmpeg_version: str | None = None


async def _ffmpeg() -> str | None:
    """ "ffmpeg 7.1.2" (asked once), None when not installed."""
    global _ffmpeg_version
    if _ffmpeg_version is not None:
        return _ffmpeg_version or None
    path = _ffmpeg_path()
    if path is None:
        _ffmpeg_version = ""
        return None
    try:
        process = await asyncio.create_subprocess_exec(
            path,
            "-version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        output, _ = await asyncio.wait_for(process.communicate(), timeout=5)
    except (OSError, TimeoutError):
        return None
    first = output.decode(errors="replace").splitlines()[0] if output else ""
    # "ffmpeg version 7.1.2-0+deb13u1 Copyright (c) 2000-2025 ..." -> "ffmpeg 7.1.2-0+deb13u1"
    words = first.split()
    _ffmpeg_version = f"ffmpeg {words[2]}" if len(words) > 2 and words[1] == "version" else first
    return _ffmpeg_version or None


@cache
def _in_container() -> bool:
    return Path("/.dockerenv").exists()


# What cannot change while the server runs, read once (only the uptime is computed on
# each request).
_runtime: Runtime | None = None


async def runtime(session: AsyncSession) -> Runtime:
    global _runtime
    if _runtime is None:
        try:
            postgres = await session.scalar(text("SHOW server_version"))
        except Exception:  # an exotic database: the page still answers
            postgres = None
        found = Runtime(
            version=__version__,
            python=f"{platform.python_implementation()} {platform.python_version()}",
            os=_os_name(),
            kernel=f"{platform.system()} {platform.release()}",
            architecture=platform.machine(),
            container=_in_container(),
            cpus=os.cpu_count(),
            postgres=f"PostgreSQL {postgres}" if postgres else None,
            ffmpeg=await _ffmpeg(),
            time_zone=os.environ.get("TZ") or time.tzname[0],
            started_at=STARTED_AT,
            uptime_s=0,
        )
        if found.postgres is None:
            return replace(found, uptime_s=_uptime())  # asked again next time
        _runtime = found
    return replace(_runtime, uptime_s=_uptime())


def _uptime() -> int:
    return int(time.monotonic() - _started)


async def warm_up() -> None:
    """At start-up, in the background: the library list (reads every installed
    package's metadata) and ffmpeg's version, so the About page answers at once."""
    await asyncio.to_thread(libraries)
    await _ffmpeg()
