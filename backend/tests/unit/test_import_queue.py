from pathlib import Path
from typing import Any, cast

from app.library_manager.as_is import AsIsTagger
from app.library_manager.imports import ImportManager


def test_decisions_go_before_queued_matching(tmp_path: Path) -> None:
    manager = ImportManager(cast(Any, None), cast(Any, None), AsIsTagger(), tmp_path)
    manager._enqueue("job", 1)  # e.g. "Add all to beets": hundreds of albums to match
    for task_id in (10, 11, 12):
        manager._enqueue("identify", task_id)
    manager._enqueue("apply", 5)  # then an admin applies a match
    manager._enqueue("identify", 6, urgent=True)  # and retries one album by hand
    manager._enqueue("apply", 13, urgent=False)  # a bulk decision waits its turn
    order = [manager._queue.get_nowait()[2:] for _ in range(manager._queue.qsize())]
    assert order == [
        ("apply", 5),
        ("identify", 6),
        ("job", 1),
        ("identify", 10),
        ("identify", 11),
        ("identify", 12),
        ("apply", 13),
    ]
