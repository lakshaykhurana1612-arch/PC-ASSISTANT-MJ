"""
Lightweight Event Bus — publish/subscribe skeleton.

Currently provides:
- Simple synchronous pub/sub for pipeline observability
- No external dependencies
- Future: async delivery, persistence, distributed events

Usage:
    bus = get_event_bus()
    bus.subscribe("pipeline.*", my_handler)
    bus.publish(some_event)
"""

from __future__ import annotations

import fnmatch
import logging
import threading
import time
from typing import Any, Callable

from app.events.events import MJEvent

logger = logging.getLogger(__name__)

# Type for event handlers
EventHandler = Callable[[MJEvent], None]


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------


class EventBus:
    """Simple synchronous event bus.

    Thread-safe for subscribe/unsubscribe/publish.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._wildcard_subscribers: list[tuple[str, EventHandler]] = []

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        """Subscribe to an event by name.

        Supports wildcards: 'pipeline.*' matches 'pipeline.normalize', etc.
        Also supports exact names: 'intent.chat'

        Args:
            event_name: event name or pattern (supports * wildcard)
            handler: callable receiving MJEvent
        """
        with self._lock:
            if "*" in event_name:
                self._wildcard_subscribers.append((event_name, handler))
            else:
                if event_name not in self._subscribers:
                    self._subscribers[event_name] = []
                self._subscribers[event_name].append(handler)

    def unsubscribe(self, event_name: str, handler: EventHandler) -> None:
        """Remove a subscriber."""
        with self._lock:
            if "*" in event_name:
                self._wildcard_subscribers = [
                    (p, h) for p, h in self._wildcard_subscribers
                    if not (p == event_name and h == handler)
                ]
            else:
                if event_name in self._subscribers:
                    self._subscribers[event_name] = [
                        h for h in self._subscribers[event_name] if h != handler
                    ]

    def publish(self, event: MJEvent) -> None:
        """Publish an event to all matching subscribers.

        Args:
            event: MJEvent instance to publish
        """
        event.timestamp = time.time()

        handlers: list[EventHandler] = []

        with self._lock:
            # Exact match
            if event.name in self._subscribers:
                handlers.extend(self._subscribers[event.name])

            # Wildcard match
            for pattern, handler in self._wildcard_subscribers:
                if fnmatch.fnmatch(event.name, pattern):
                    handlers.append(handler)

        # Execute handlers outside lock
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Event handler error for '{event.name}': {e}")

    def clear(self) -> None:
        """Remove all subscribers (for testing/reset)."""
        with self._lock:
            self._subscribers.clear()
            self._wildcard_subscribers.clear()

    @property
    def subscriber_count(self) -> int:
        """Number of registered handlers."""
        with self._lock:
            exact = sum(len(h) for h in self._subscribers.values())
            wild = len(self._wildcard_subscribers)
            return exact + wild


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_GLOBAL_EVENT_BUS: EventBus | None = None
_GLOBAL_LOCK = threading.Lock()


def get_event_bus() -> EventBus:
    """Get the global EventBus singleton."""
    global _GLOBAL_EVENT_BUS
    if _GLOBAL_EVENT_BUS is None:
        with _GLOBAL_LOCK:
            if _GLOBAL_EVENT_BUS is None:
                _GLOBAL_EVENT_BUS = EventBus()
    return _GLOBAL_EVENT_BUS

