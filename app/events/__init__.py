"""
MJ Event System — Lightweight event bus for pipeline communication.

Provides:
- Event dataclasses for all pipeline stages
- EventBus: publish/subscribe skeleton for future extensibility
- Pre/post event hooks for middleware integration
"""

from app.events.events import (
    MJEvent,
    PipelineEvent,
    IntentEvent,
    PlanEvent,
    ExecutionEvent,
    ResponseEvent,
    ErrorEvent,
)
from app.events.event_bus import EventBus, get_event_bus

__all__ = [
    "MJEvent",
    "PipelineEvent",
    "IntentEvent",
    "PlanEvent",
    "ExecutionEvent",
    "ResponseEvent",
    "ErrorEvent",
    "EventBus",
    "get_event_bus",
]

