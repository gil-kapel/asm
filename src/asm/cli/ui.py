"""Terminal UI utilities — spinner, progress."""

from __future__ import annotations

import contextlib
import itertools
import sys
import threading


@contextlib.contextmanager
def spinner():
    """Yield a callable that updates an inline spinner with status text."""
    frames = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
    message: str = ""
    lock = threading.Lock()
    done = threading.Event()

    def _update(msg: str) -> None:
        nonlocal message
        with lock:
            message = msg

    def _draw() -> None:
        while not done.is_set():
            with lock:
                text = message
            if text:
                sys.stderr.write(f"\r{next(frames)} {text}\033[K")
                sys.stderr.flush()
            done.wait(0.08)
        sys.stderr.write("\r\033[K")
        sys.stderr.flush()

    t = threading.Thread(target=_draw, daemon=True)
    t.start()
    try:
        yield _update
    finally:
        done.set()
        t.join()
