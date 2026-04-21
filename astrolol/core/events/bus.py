import asyncio
from collections import deque

import structlog

from astrolol.core.events.models import BaseEvent

logger = structlog.get_logger()

HISTORY_SIZE = 10_000


class EventBus:
    """
    Async pub/sub bus. Publishers call publish(). Each WebSocket client
    calls subscribe() to get a queue, then reads from it in a loop.
    Call unsubscribe() on disconnect to avoid leaking queues.

    A ring buffer of the last HISTORY_SIZE events is kept so late-connecting
    or reconnecting clients can replay what they missed.
    """

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[BaseEvent]] = []
        self._history: deque[BaseEvent] = deque(maxlen=HISTORY_SIZE)

    def subscribe(self) -> asyncio.Queue[BaseEvent]:
        q: asyncio.Queue[BaseEvent] = asyncio.Queue()
        self._subscribers.append(q)
        logger.debug("eventbus.subscribed", total=len(self._subscribers))
        return q

    def unsubscribe(self, q: asyncio.Queue[BaseEvent]) -> None:
        try:
            self._subscribers.remove(q)
            logger.debug("eventbus.unsubscribed", total=len(self._subscribers))
        except ValueError:
            pass  # already removed, safe to ignore

    async def publish(self, event: BaseEvent) -> None:
        logger.debug("eventbus.publish", event_type=event.type, event_id=event.id)  # type: ignore[attr-defined]
        self._history.append(event)
        for q in self._subscribers:
            await q.put(event)

    def get_history(self) -> list[BaseEvent]:
        """Return a snapshot of the ring buffer, oldest first."""
        return list(self._history)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
