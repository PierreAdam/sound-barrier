"""The signed-in user's web UI preferences (theme, player)."""

from fastapi import APIRouter

from app.api.deps import CurrentCaller, DbSession
from app.services import preferences
from app.services.preferences import Preferences

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("", response_model_by_alias=True)
async def get_preferences(caller: CurrentCaller) -> Preferences:
    return preferences.get(caller.user)


@router.put("", response_model_by_alias=True)
async def set_preferences(
    body: Preferences, caller: CurrentCaller, session: DbSession
) -> Preferences:
    """Replaces the preferences (the web UI always sends all of them)."""
    # `caller` was loaded in this same request session (FastAPI caches dependencies).
    saved = await preferences.save(session, caller.user, body)
    await session.commit()
    return saved
