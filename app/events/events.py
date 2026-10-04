"""
Event type definitions for the MJ pipeline.

Every stage of the pipeline emits events for observability, logging,
and future middleware/plugin support.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Event categories
# ---------------------------------------------------------------------------


class EventCategory(Enum):
    """Top-level event categories."""

    PIPELINE = auto()
    INTENT = auto()
    PLAN = auto()
    EXECUTION = auto()
    RESPONSE = auto()
    ERROR = auto()
    SYSTEM = auto()


# ---------------------------------------------------------------------------
# Base event
# ---------------------------------------------------------------------------


@dataclass
class MJEvent:
    """Base event for all MJ events."""

    category: EventCategory
    name: str
    data: Any = None
    source: str = ""
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Pipeline events
# ---------------------------------------------------------------------------


@dataclass
class PipelineEvent(MJEvent):
    """Events emitted during pipeline execution."""

    stage: str = ""  # normalize, route, context, plan, prompt, validate, execute, respond
    input_text: str = ""
    duration_ms: float = 0.0

    def __init__(
        self,
        stage: str,
        input_text: str = "",
        data: Any = None,
        duration_ms: float = 0.0,
        **kwargs,
    ):
        super().__init__(
            category=EventCategory.PIPELINE,
            name=f"pipeline.{stage}",
            data=data,
            **kwargs,
        )
        self.stage = stage
        self.input_text = input_text
        self.duration_ms = duration_ms


# ---------------------------------------------------------------------------
# Intent events
# ---------------------------------------------------------------------------


@dataclass
class IntentEvent(MJEvent):
    """Emitted after intent routing."""

    intent: str = ""
    confidence: float = 0.0
    raw_text: str = ""
    normalized_text: str = ""

    def __init__(self, intent: str = "", **kwargs):
        super().__init__(category=EventCategory.INTENT, name=f"intent.{intent}", **kwargs)
        self.intent = intent


# ---------------------------------------------------------------------------
# Plan events
# ---------------------------------------------------------------------------


@dataclass
class PlanEvent(MJEvent):
    """Emitted when a plan is created, validated, or executed."""

    plan_id: str = ""
    task_count: int = 0
    status: str = ""  # created, validated, executing, completed, failed

    def __init__(self, status: str = "", **kwargs):
        super().__init__(category=EventCategory.PLAN, name=f"plan.{status}", **kwargs)
        self.status = status


# ---------------------------------------------------------------------------
# Execution events
# ---------------------------------------------------------------------------


@dataclass
class ExecutionEvent(MJEvent):
    """Emitted for each tool/step execution."""

    tool: str = ""
    status: str = ""  # started, success, failed
    result: Any = None
    error: Optional[str] = None

    def __init__(self, tool: str = "", status: str = "", **kwargs):
        super().__init__(
            category=EventCategory.EXECUTION,
            name=f"execute.{tool}.{status}",
            **kwargs,
        )
        self.tool = tool
        self.status = status


# ---------------------------------------------------------------------------
# Response events
# ---------------------------------------------------------------------------


@dataclass
class ResponseEvent(MJEvent):
    """Emitted when a response is ready."""

    text: str = ""
    has_speech: bool = False
    source_intent: str = ""

    def __init__(self, text: str = "", **kwargs):
        super().__init__(category=EventCategory.RESPONSE, name="response", **kwargs)
        self.text = text


# ---------------------------------------------------------------------------
# Error events
# ---------------------------------------------------------------------------


@dataclass
class ErrorEvent(MJEvent):
    """Emitted on pipeline errors."""

    error_type: str = ""
    message: str = ""
    recoverable: bool = False
    traceback_str: str = ""

    def __init__(self, error_type: str = "", **kwargs):
        super().__init__(category=EventCategory.ERROR, name=f"error.{error_type}", **kwargs)
        self.error_type = error_type

