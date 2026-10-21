"""Request-scoped cancellation for the local dashboard's streaming chats."""

import re
import threading
from contextlib import contextmanager

from pu.core.cancellation import RunCancelled

_lock = threading.Lock()
_runs: dict[str, threading.Event] = {}


@contextmanager
def active_chat(request_id):
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,80}", request_id):
        raise ValueError("Invalid chat request ID")
    event = threading.Event()
    with _lock:
        if request_id in _runs:
            raise ValueError("Chat request ID is already active")
        _runs[request_id] = event
    try:
        yield event
    finally:
        with _lock:
            _runs.pop(request_id, None)


def stop_chat(request_id):
    with _lock:
        event = _runs.get(request_id) if isinstance(request_id, str) else None
        if event is not None:
            event.set()
        return event is not None


def check_cancelled(event):
    if event is not None and event.is_set():
        raise RunCancelled()


@contextmanager
def chat_lock(lock, event):
    while not lock.acquire(timeout=0.1):
        check_cancelled(event)
    try:
        check_cancelled(event)
        yield
    finally:
        lock.release()
