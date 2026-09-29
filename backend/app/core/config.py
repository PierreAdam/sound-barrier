from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOUND_BARRIER_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://soundbarrier:soundbarrier@localhost:5432/soundbarrier"
    # Fernet key encrypting user passwords. Optional here so that tools which do not
    # touch passwords (e.g. migrations) can run without it; checked where it is needed.
    secret_key: SecretStr | None = None
    data_dir: Path = Path("./data")
    log_level: str = "info"
    # Automatic scans (at startup and daily, configured in Settings). False disables them.
    scheduler: bool = True
    # Files whose tags are read in parallel. Raise it for network drives (high latency).
    scan_workers: int = 4
    # Built web UI (frontend/dist) served at `/`. None: API only (development uses Vite).
    web_dir: Path | None = None
    # Applied once, when nothing is configured yet (first start of a Docker container):
    # the library folder and the import root folder. Both can be changed in Settings.
    initial_library_dir: Path | None = None
    initial_import_dir: Path | None = None
    # Podcasts and audiobooks folders (optional; their sections stay off until an admin
    # turns them on in Settings).
    initial_podcasts_dir: Path | None = None
    initial_audiobooks_dir: Path | None = None
    # Failed sign-ins (web and Subsonic API) from one IP address before it is refused for
    # login_block_minutes (the failures are counted over the same duration).
    login_max_failures: int = 10
    login_block_minutes: int = 15
    # Tagging engine of imports: beets (MusicBrainz matching) or the current tags only.
    tagger: Literal["beets", "as-is"] = "beets"
    # beets configuration (optional config.yaml) and database. None: <data_dir>/beets.
    beets_dir: Path | None = None

    def require_secret_key(self) -> str:
        if self.secret_key is None or not self.secret_key.get_secret_value():
            raise RuntimeError(
                "SOUND_BARRIER_SECRET_KEY is not set. Generate one with `sound-barrier gen-secret`."
            )
        return self.secret_key.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    return Settings()
