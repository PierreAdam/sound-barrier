"""The About page: the server's libraries (everyone), its runtime (admins)."""

from datetime import datetime

from fastapi import APIRouter

from app.api.deps import ApiModel, CurrentCaller, DbSession
from app.services import about

router = APIRouter(tags=["about"])


class LibraryOut(ApiModel):
    name: str
    version: str
    license: str | None
    summary: str | None
    url: str | None
    direct: bool  # declared by Sound-Barrier (else needed by another library)


class RuntimeOut(ApiModel):
    version: str
    python: str
    os: str
    kernel: str
    architecture: str
    container: bool
    cpus: int | None
    postgres: str | None
    ffmpeg: str | None
    time_zone: str
    started_at: datetime
    uptime_s: int


class AboutOut(ApiModel):
    libraries: list[LibraryOut]
    # Admins only: exact versions of the server's software are not for every account.
    runtime: RuntimeOut | None


@router.get("/about")
async def get_about(caller: CurrentCaller, session: DbSession) -> AboutOut:
    runtime = await about.runtime(session) if caller.user.is_admin else None
    return AboutOut(
        libraries=[LibraryOut(**vars(lib)) for lib in about.libraries()],
        runtime=RuntimeOut(**vars(runtime)) if runtime else None,
    )
