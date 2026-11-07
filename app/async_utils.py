"""Helpers for running async code from synchronous contexts (e.g. Flask)."""

import asyncio
import threading

_loop = None
_lock = threading.Lock()


def _get_loop():
    """Get or create a dedicated event loop, one per thread."""
    global _loop
    if _loop is None:
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop


def run_async(coro):
    """Run an async coroutine from synchronous code.

    Creates a dedicated event loop and runs it until completion.
    The loop persists for reuse within the same thread.
    """
    loop = _get_loop()
    if loop.is_running():
        raise RuntimeError(
            "Cannot run async from a running event loop. "
            "Use threading or move to an async context."
        )
    return loop.run_until_complete(coro)
