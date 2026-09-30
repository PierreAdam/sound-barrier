import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api import build_router as build_api_router
from app.core.config import Settings, get_settings
from app.core.crypto import PasswordCipher
from app.core.db import Database
from app.core.logging import configure_logging
from app.core.throttle import LoginThrottle
from app.external import create_client
from app.library_manager import get_tagger
from app.library_manager.imports import ImportManager
from app.services import about, first_start, users
from app.services.maintenance import LibraryRoot, Maintenance
from app.services.new_releases import DiscographySync
from app.services.remote import RemoteHub
from app.services.scans import ScanManager
from app.subsonic import build_router
from app.web import mount_web


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        db = Database(settings.database_url)
        app.state.db = db
        app.state.http = http = create_client()  # external services (Last.fm...)
        async with db.session() as session:
            await users.ensure_default_admin(session, app.state.cipher)
            await first_start.apply_initial_folders(
                session,
                library_dir=settings.initial_library_dir,
                import_dir=settings.initial_import_dir,
                podcasts_dir=settings.initial_podcasts_dir,
                audiobooks_dir=settings.initial_audiobooks_dir,
            )
            await session.commit()
        app.state.scans = scans = ScanManager(db, workers=settings.scan_workers)
        app.state.imports = imports = ImportManager(
            db,
            scans,
            get_tagger(settings),
            staging_root=settings.data_dir / "import-staging",
            http=lambda: app.state.http,
        )
        await imports.start()
        app.state.discography_sync = discography_sync = DiscographySync(db)
        app.state.maintenance = maintenance = Maintenance(
            db, imports, settings.data_dir, settings.beets_dir or settings.data_dir / "beets"
        )
        cleanups = None
        if settings.scheduler:
            cleanups = asyncio.create_task(
                maintenance.run_forever(LibraryRoot(db)), name="maintenance"
            )
        scheduler = None
        if settings.scheduler:
            scheduler = asyncio.create_task(scans.run_scheduler(), name="scan-scheduler")
        # The About page's library list and ffmpeg version, ready before anyone asks.
        warm_up = asyncio.create_task(about.warm_up(), name="about-warm-up")
        yield
        warm_up.cancel()
        if scheduler is not None:
            scheduler.cancel()
        if cleanups is not None:
            cleanups.cancel()
        await discography_sync.stop()
        await imports.stop()
        await scans.stop()
        await http.aclose()
        await db.dispose()

    app = FastAPI(title="Sound-Barrier", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.cipher = PasswordCipher(settings.require_secret_key())
    app.state.remote = RemoteHub()  # remote control (in memory: one server process)
    app.state.throttle = LoginThrottle(
        settings.login_max_failures,
        window_seconds=settings.login_block_minutes * 60,
        block_seconds=settings.login_block_minutes * 60,
    )
    app.include_router(build_router(), prefix="/rest")
    app.include_router(build_api_router(), prefix="/api")
    if settings.web_dir is not None:
        mount_web(app, settings.web_dir)  # last: its catch-all route must not shadow the APIs
    return app
