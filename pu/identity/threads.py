"""Start background work without dropping the caller's principal.

``contextvars`` do not cross a raw ``threading.Thread`` boundary. Worker
threads copy the context that was current when they were started, so a
principal attached on the request is still attached inside the job.
"""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Callable


def spawn_inheriting(
    target: Callable[[], None],
    *,
    name: str,
    daemon: bool = True,
) -> threading.Thread:
    """Run ``target`` on a daemon thread that inherits the current context."""
    context = contextvars.copy_context()

    def runner() -> None:
        context.run(target)

    thread = threading.Thread(target=runner, name=name, daemon=daemon)
    thread.start()
    return thread
