import asyncio
import structlog

from astrolol.core.events.models import BaseEvent

logger = structlog.get_logger()


class EventBus:
    """
    Async pub/sub bus. Publishers call publish(). Each WebSocket client
    calls subscribe() to get a queue, then reads from it in a loop.
    Call unsubscribe() on disconnect to avoid leaking queues.
    """

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[BaseEvent]] = []

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
        for q in self._subscribers:
            await q.put(event)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
