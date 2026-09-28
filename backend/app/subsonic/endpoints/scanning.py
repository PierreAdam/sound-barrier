from app.services import scans
from app.services.scans import ScanManager
from app.subsonic import schemas
from app.subsonic.envelope import Payload
from app.subsonic.errors import SubsonicError
from app.subsonic.router import SubsonicContext, registry


async def _status(ctx: SubsonicContext) -> Payload:
    manager: ScanManager = ctx.request.app.state.scans
    scan = await scans.latest_scan(ctx.session)
    # The scan task may not have created its `scan` row yet, hence `manager.running`.
    running_row = scan is not None and scan.status == "running"
    scanning = manager.running or running_row
    if scanning:
        count = scan.files_seen if scan is not None and running_row else 0
    else:
        count = await scans.count_present_songs(ctx.session)
    return {
        "scanStatus": schemas.ScanStatus(
            scanning=scanning,
            count=count,
            last_scan=scan.finished_at if scan is not None else None,
        )
    }


@registry.endpoint("getScanStatus")
async def get_scan_status(ctx: SubsonicContext) -> Payload:
    return await _status(ctx)


@registry.endpoint("startScan")
async def start_scan(ctx: SubsonicContext) -> Payload:
    if not ctx.user.is_admin:
        raise SubsonicError.not_authorized("Only admins can start a scan")
    manager: ScanManager = ctx.request.app.state.scans
    # `fullScan=true` (Navidrome extension) re-reads every file.
    manager.start(full=ctx.params.get_bool("fullScan"))
    return await _status(ctx)
