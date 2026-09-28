"""Library management (Manage Library page): import, review, delete.

The tagging engine is behind `Tagger` (tagger.py); `get_tagger()` picks the one to use.
"""

from app.core.config import Settings
from app.library_manager.as_is import AsIsTagger
from app.library_manager.beets_tagger import BeetsTagger, beets_available
from app.library_manager.tagger import Tagger


def get_tagger(settings: Settings) -> Tagger:
    """beets (MusicBrainz matching) unless disabled or not installed, else imports with
    the current tags."""
    if settings.tagger == "beets" and beets_available():
        return BeetsTagger(settings.beets_dir or settings.data_dir / "beets")
    return AsIsTagger()
