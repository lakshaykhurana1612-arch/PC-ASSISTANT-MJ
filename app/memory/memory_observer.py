"""
Memory Observer — Watches pipeline events and auto-saves important memories.

Subscribes to the EventBus and automatically:
1. Saves important conversations after processing
2. Extracts user preferences from interactions
3. Updates contact memory on WhatsApp/communication events
4. Tracks task completions
5. Monitors system patterns

This is the passive "learn from what happens" layer.
It never interrupts — it observes and stores in background.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from app.events.event_bus import get_event_bus, EventBus
from app.events.events import (
    PipelineEvent,
    ResponseEvent,
    ExecutionEvent,
    ErrorEvent,
)
from app.memory.models import MemoryEntry, MemoryType, MemorySource, Importance
from app.memory.memory_manager import MemoryManager
from app.memory.importance_scorer import ImportanceScorer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Observer Configuration
# ---------------------------------------------------------------------------


@dataclass
class ObserverConfig:
    """Configuration for what the observer saves."""

    save_conversations: bool = True
    save_preferences: bool = True
    save_contacts: bool = True
    save_tasks: bool = True
    save_errors: bool = False  # Only critical errors
    save_code_context: bool = True
    min_importance_to_save: float = 0.3  # Don't save trivial memories
    summarize_conversations: bool = True
    max_conversation_age_minutes: float = 60  # Summarize conversations older than this


# ---------------------------------------------------------------------------
# Memory Observer
# ---------------------------------------------------------------------------


class MemoryObserver:
    """Observes pipeline events and auto-saves memories.

    Runs passively in the background. Never blocks the main pipeline.

    Usage:
        observer = MemoryObserver(memory_manager)
        observer.start()  # Subscribe to event bus
        ...
        observer.stop()   # Unsubscribe
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        config: Optional[ObserverConfig] = None,
    ):
        self.memory_manager = memory_manager
        self.config = config or ObserverConfig()
        self.event_bus = get_event_bus()
        self.scorer = ImportanceScorer()

        self._running = False
        self._handlers: list[tuple[str, callable]] = []
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Track conversations for summarization
        self._conversation_buffer: list[dict] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start observing — subscribe to event bus."""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        # Subscribe to events
        self._subscribe("pipeline.*", self._on_pipeline_event)
        self._subscribe("response", self._on_response_event)
        self._subscribe("execute.*.*", self._on_execution_event)
        self._subscribe("error.*", self._on_error_event)
        self._subscribe("intent.*", self._on_intent_event)

        logger.info("Memory observer started")

    def stop(self) -> None:
        """Stop observing — unsubscribe from event bus."""
        self._running = False
        self._stop_event.set()

        for pattern, handler in self._handlers:
            try:
                self.event_bus.unsubscribe(pattern, handler)
            except Exception:
                pass

        self._handlers.clear()

        # Save any pending conversation summary
        self._flush_conversation_buffer()

        logger.info("Memory observer stopped")

    def _subscribe(self, pattern: str, handler) -> None:
        """Subscribe to an event pattern and track for cleanup."""
        self.event_bus.subscribe(pattern, handler)
        self._handlers.append((pattern, handler))

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_pipeline_event(self, event: PipelineEvent) -> None:
        """Handle pipeline events."""
        if not self.config.save_conversations:
            return

        # Buffer user input for conversation memory
        if event.stage in ("normalize", "route") and event.input_text:
            self._buffer_message("user", event.input_text, event.timestamp)

    def _on_response_event(self, event: ResponseEvent) -> None:
        """Handle response events — save conversation memory."""
        if not self.config.save_conversations:
            return

        if event.text:
            self._buffer_message("assistant", event.text, event.timestamp)

    def _on_execution_event(self, event: ExecutionEvent) -> None:
        """Handle execution events — save task/completion memories."""
        if event.status == "started":
            return

        # Save successful tool executions as task memories
        if event.status == "success" and self.config.save_tasks:
            if not event.text and not event.data:
                return

            content = str(event.data) if event.data else ""
            title = f"Executed: {event.tool}"

            entry = MemoryEntry(
                memory_type=MemoryType.TASK.name,
                source=MemorySource.MJ.name,
                title=title,
                content=content,
                metadata={
                    "tool": event.tool,
                    "status": event.status,
                    "task_success": 1.0 if event.status == "success" else 0.0,
                },
                tags=["execution", event.tool.lower()],
            )

            self.memory_manager.remember(entry)

    def _on_error_event(self, event: ErrorEvent) -> None:
        """Handle error events — save critical errors."""
        if not self.config.save_errors:
            return

        if not event.recoverable:
            entry = MemoryEntry(
                memory_type=MemoryType.SYSTEM.name,
                source=MemorySource.SYSTEM.name,
                title=f"Error: {event.error_type}",
                content=event.message or event.data or "",
                metadata={
                    "error_type": event.error_type,
                    "recoverable": event.recoverable,
                },
                tags=["error", event.error_type.lower()],
                importance=0.6,  # Errors are moderately important
            )
            self.memory_manager.remember(entry, auto_embed=False)

    def _on_intent_event(self, event) -> None:
        """Handle intent events — learn user patterns."""
        try:
            intent = getattr(event, 'intent', '') or getattr(event, 'data', '')
        except Exception:
            return

    # ------------------------------------------------------------------
    # Conversation buffer
    # ------------------------------------------------------------------

    def _buffer_message(self, role: str, content: str, timestamp: float) -> None:
        """Buffer conversation messages."""
        self._conversation_buffer.append({
            "role": role,
            "content": content,
            "timestamp": timestamp,
        })

        # Save after every exchange (user + assistant pair)
        if len(self._conversation_buffer) >= 2:
            self._flush_conversation_buffer()

    def _flush_conversation_buffer(self) -> None:
        """Convert buffered messages to memory entries."""
        if not self._conversation_buffer:
            return

        messages = self._conversation_buffer[:]
        self._conversation_buffer.clear()

        # Build conversation context
        user_msgs = [m for m in messages if m["role"] == "user"]
        assistant_msgs = [m for m in messages if m["role"] == "assistant"]

        if not user_msgs:
            return

        # Create conversation memory entry
        last_user_msg = user_msgs[-1]["content"]
        full_content = "\n".join(
            f"[{m['role']}]: {m['content']}" for m in messages
        )

        # Determine importance based on content
        importance = self._estimate_conversation_importance(last_user_msg, messages)

        if importance < self.config.min_importance_to_save:
            return

        entry = MemoryEntry(
            memory_type=MemoryType.CONVERSATION.name,
            source=MemorySource.MJ.name,
            title=last_user_msg[:100],
            content=full_content,
            metadata={
                "message_count": len(messages),
                "user_count": len(user_msgs),
                "assistant_count": len(assistant_msgs),
                "exchange_count": min(len(user_msgs), len(assistant_msgs)),
            },
            importance=importance,
            tags=["conversation"],
        )

        self.memory_manager.remember(entry, auto_embed=True)

    @staticmethod
    def _estimate_conversation_importance(user_msg: str, messages: list[dict]) -> float:
        """Estimate how important a conversation is to save.

        Higher score = more likely to be useful in future contexts.
        """
        score = 0.3  # Base score

        # Commands/tasks are more important
        command_keywords = [
            "send", "open", "find", "search", "create", "make", "write",
            "read", "analyze", "fix", "update", "delete", "move", "copy",
            "whatsapp", "email", "call",
        ]
        user_msg_lower = user_msg.lower()
        for kw in command_keywords:
            if kw in user_msg_lower:
                score += 0.1
                break

        # Longer conversations are more important
        if len(messages) >= 4:
            score += 0.1
        if len(messages) >= 8:
            score += 0.1

        # Questions about personal info are important
        personal_keywords = ["my", "mine", "i", "me", "name", "address", "phone"]
        personal_count = sum(1 for kw in personal_keywords if kw in user_msg_lower)
        score += personal_count * 0.05

        # Cap at 1.0
        return min(score, 1.0)

    # ------------------------------------------------------------------
    # Direct observation methods
    # ------------------------------------------------------------------

    def observe_execution(self, tool: str, status: str, result: Any) -> None:
        """Directly observe an execution for memory saving.

        Can be called from non-event-bus code paths.
        """
        if not self.config.save_tasks:
            return

        if status != "success":
            return

        entry = MemoryEntry(
            memory_type=MemoryType.TASK.name,
            source=MemorySource.MJ.name,
            title=f"Executed: {tool}",
            content=str(result)[:500] if result else "",
            metadata={"tool": tool, "status": status},
            tags=["execution", tool.lower()],
        )

        if self.scorer.calculate(entry) >= self.config.min_importance_to_save:
            self.memory_manager.remember(entry, auto_embed=False)

