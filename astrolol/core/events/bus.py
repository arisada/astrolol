import asyncio
from collections import deque

import structlog

from astrolol.core.events.models import BaseEvent

logger = structlog.get_logger()

HISTORY_SIZE = 10_000
# Queue depth for remote clients (WebSocket). A stalled client loses its oldest
# events instead of growing the server's memory without limit.
CLIENT_QUEUE_SIZE = 5_000


class EventBus:
    """
    Async pub/sub bus. Publishers call publish(). Each WebSocket client
    calls subscribe() to get a queue, then reads from it in a loop.
    Call unsubscribe() on disconnect to avoid leaking queues.

    Subscribers are unbounded by default (in-process consumers must not lose
    events). Pass ``maxsize`` for a slow-prone consumer: when its queue is full
    the oldest event is dropped to make room, and the drop is counted.

    A ring buffer of the last HISTORY_SIZE events is kept so late-connecting
    or reconnecting clients can replay what they missed.
    """

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[BaseEvent]] = []
        self._history: deque[BaseEvent] = deque(maxlen=HISTORY_SIZE)
        self._dropped: dict[int, int] = {}  # id(queue) -> events dropped
        self.dropped_total = 0

    def subscribe(self, maxsize: int = 0) -> asyncio.Queue[BaseEvent]:
        q: asyncio.Queue[BaseEvent] = asyncio.Queue(maxsize=maxsize)
        self._subscribers.append(q)
        logger.debug("eventbus.subscribed", total=len(self._subscribers))
        return q

    def unsubscribe(self, q: asyncio.Queue[BaseEvent]) -> None:
        self._dropped.pop(id(q), None)
        try:
            self._subscribers.remove(q)
            logger.debug("eventbus.unsubscribed", total=len(self._subscribers))
        except ValueError:
            pass  # already removed, safe to ignore

    async def publish(self, event: BaseEvent) -> None:
        logger.debug("eventbus.publish", event_type=event.type, event_id=event.id)  # type: ignore[attr-defined]
        self._history.append(event)
        for q in self._subscribers:
            if q.full():
                q.get_nowait()  # only bounded queues can be full: drop the oldest
                n = self._dropped[id(q)] = self._dropped.get(id(q), 0) + 1
                self.dropped_total += 1
                if n == 1 or n % 1000 == 0:
                    logger.warning("eventbus.subscriber_slow", dropped=n)
            q.put_nowait(event)

    def get_history(self) -> list[BaseEvent]:
        """Return a snapshot of the ring buffer, oldest first."""
        return list(self._history)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
