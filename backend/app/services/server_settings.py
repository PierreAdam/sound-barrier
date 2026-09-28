"""Settings changed from the web UI, stored in the `server_setting` table."""

import re

from pydantic import BaseModel, field_validator
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ServerSetting

SCAN_SCHEDULE_KEY = "scan_schedule"
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ScanSchedule(BaseModel):
    """Automatic library scans. `time` is the server's local time (HH:MM)."""

    enabled: bool = True
    time: str = "02:00"
    scan_on_startup: bool = True

    @field_validator("time")
    @classmethod
    def _check_time(cls, value: str) -> str:
        if not _TIME.match(value):
            raise ValueError("time must be HH:MM (00:00 to 23:59)")
        return value

    @property
    def hour_minute(self) -> tuple[int, int]:
        hour, minute = self.time.split(":")
        return int(hour), int(minute)


IMPORT_SETTINGS_KEY = "import_settings"


class ImportSettings(BaseModel):
    """Import options (Settings page). `root` is the only folder the Manage Library page
    can browse and import from (e.g. the downloads folder)."""

    root: str | None = None  # absolute path on the server
    mode: str = "copy"  # copy (sources kept) or move
    auto_apply_strong: bool = True  # import confident matches without review
    # Convert lossless files (FLAC, WAV...) to MP3 with ffmpeg while importing.
    transcode_lossless: bool = False


async def get_import_settings(session: AsyncSession) -> ImportSettings:
    row = await session.get(ServerSetting, IMPORT_SETTINGS_KEY)
    return ImportSettings() if row is None else ImportSettings.model_validate(row.value)


async def set_import_settings(session: AsyncSession, settings: ImportSettings) -> None:
    value = settings.model_dump()
    statement = insert(ServerSetting).values(key=IMPORT_SETTINGS_KEY, value=value)
    await session.execute(
        statement.on_conflict_do_update(index_elements=[ServerSetting.key], set_={"value": value})
    )


async def get_scan_schedule(session: AsyncSession) -> ScanSchedule:
    row = await session.get(ServerSetting, SCAN_SCHEDULE_KEY)
    if row is None:
        return ScanSchedule()
    return ScanSchedule.model_validate(row.value)


async def set_scan_schedule(session: AsyncSession, schedule: ScanSchedule) -> None:
    value = schedule.model_dump()
    statement = insert(ServerSetting).values(key=SCAN_SCHEDULE_KEY, value=value)
    await session.execute(
        statement.on_conflict_do_update(index_elements=[ServerSetting.key], set_={"value": value})
    )


EXTERNAL_SERVICES_KEY = "external_services"


class ExternalServices(BaseModel):
    """Artist information (Last.fm), pictures and discographies (MusicBrainz). API keys
    are stored encrypted with the server's secret key (`*_key_enc`, Fernet tokens), never
    sent back to the web UI."""

    lastfm_key_enc: str | None = None
    fanart_key_enc: str | None = None
    picture_source: str = "deezer"  # "none" or an app.external.pictures provider id
    musicbrainz: bool = True  # artist discographies ("Missing albums")


async def get_external_services(session: AsyncSession) -> ExternalServices:
    row = await session.get(ServerSetting, EXTERNAL_SERVICES_KEY)
    return ExternalServices() if row is None else ExternalServices.model_validate(row.value)


async def set_external_services(session: AsyncSession, settings: ExternalServices) -> None:
    value = settings.model_dump()
    statement = insert(ServerSetting).values(key=EXTERNAL_SERVICES_KEY, value=value)
    await session.execute(
        statement.on_conflict_do_update(index_elements=[ServerSetting.key], set_={"value": value})
    )
