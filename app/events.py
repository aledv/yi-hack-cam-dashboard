"""In-memory pub/sub used to push real-time events (motion detections) to
every open browser tab via Server-Sent Events. Simple broadcaster: no
persistence, no Redis -- fine for a single-user LAN app with a handful of
open tabs.

The tricky part: MQTT messages arrive on a background thread (not the
asyncio event loop), so we can't just call an asyncio.Queue directly from
there. We keep a reference to the running loop and hop back onto it with
call_soon_threadsafe.
"""

import asyncio

_subscribers: set[asyncio.Queue] = set()
_loop: asyncio.AbstractEventLoop | None = None


def set_loop(loop: asyncio.AbstractEventLoop):
    global _loop
    _loop = loop


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue):
    _subscribers.discard(q)


def _broadcast(data: dict):
    for q in list(_subscribers):
        q.put_nowait(data)


def broadcast_threadsafe(data: dict):
    """Call from any thread (e.g. the MQTT callback thread)."""
    if _loop:
        _loop.call_soon_threadsafe(_broadcast, data)
