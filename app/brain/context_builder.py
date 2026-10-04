"""
Context Builder — Assembles context for the LLM prompt.

Injects:
- Current date/time
- Conversation history (recent)
- Available capabilities (from CapabilityManager)
- User preferences (from Memory System)
- Relevant memories (from Memory System via MemoryManager)

Usage:
    builder = ContextBuilder()
    ctx = builder.build(intent="search", user_input="weather in delhi")
    # ctx.as_dict() -> all context variables
    # ctx.as_prompt_block() -> formatted string for LLM prompt
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from app.brain.intent_router import IntentType
from app.brain.capability_manager import CapabilityManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Context Data
# ---------------------------------------------------------------------------


@dataclass
class PipelineContext:
    """Full pipeline context assembled for the LLM."""

    # Time
    current_time: str = ""
    current_date: str = ""
    day_of_week: str = ""

    # User input
    raw_input: str = ""
    normalized_input: str = ""
    intent: str = ""

    # Conversation
    conversation_history: list[dict] = field(default_factory=list)
    last_exchange: str = ""

    # Capabilities
    available_capabilities: str = ""
    tool_descriptions: list[dict] = field(default_factory=list)

    # Memory (from MemoryManager)
    relevant_memories: list[str] = field(default_factory=list)
    user_preferences: dict[str, Any] = field(default_factory=dict)

    # System
    mode: str = "classic"
    is_voice: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Get context as a flat dictionary for prompt injection."""
        return {
            "current_time": self.current_time,
            "current_date": self.current_date,
            "day_of_week": self.day_of_week,
            "user_input": self.normalized_input,
            "intent": self.intent,
            "conversation_history": self._format_history(),
            "available_capabilities": self.available_capabilities,
            "mode": self.mode,
        }

    def as_prompt_block(self) -> str:
        """Get context as a formatted string block for the LLM prompt."""
        parts = [
            f"Current Date: {self.current_date}",
            f"Current Time: {self.current_time}",
            f"Day: {self.day_of_week}",
            "",
            f"User Intent: {self.intent}",
            "",
            "Available Capabilities:",
            self.available_capabilities,
        ]

        if self.conversation_history:
            parts.extend([
                "",
                "Recent Conversation:",
                self._format_history(),
            ])

        if self.relevant_memories:
            parts.extend([
                "",
                "Relevant Memories:",
                "\n".join(f"  - {m}" for m in self.relevant_memories),
            ])

        parts.extend([
            "",
            f"System Mode: {self.mode}",
        ])

        return "\n".join(parts)

    def _format_history(self) -> str:
        """Format conversation history for prompt."""
        if not self.conversation_history:
            return "(no recent conversation)"
        lines = []
        for msg in self.conversation_history[-6:]:  # Last 6 messages
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            # Truncate long content
            if len(content) > 200:
                content = content[:200] + "..."
            lines.append(f"  [{role}] {content}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Context Builder
# ---------------------------------------------------------------------------


class ContextBuilder:
    """Assembles pipeline context for LLM prompt construction.

    Usage:
        builder = ContextBuilder()
        ctx = builder.build(
            normalized="weather in delhi today",
            intent=IntentType.SEARCH,
            raw_input="What's the weather in Delhi today?",
        )
    """

    def __init__(self):
        self._capability_mgr = CapabilityManager.get_instance()

    def build(
        self,
        normalized: str,
        intent: IntentType,
        raw_input: str = "",
        conversation_history: Optional[list[dict]] = None,
        mode: str = "classic",
        is_voice: bool = False,
    ) -> PipelineContext:
        """Build the full context for the current request.

        Args:
            normalized: normalized user input text
            intent: classified intent
            raw_input: original raw input
            conversation_history: recent conversation messages
            mode: current system mode (classic, streaming, duplex)
            is_voice: whether this was a voice input

        Returns:
            PipelineContext with all assembled context
        """
        now = datetime.datetime.now()

        ctx = PipelineContext(
            current_time=now.strftime("%I:%M %p"),
            current_date=now.strftime("%A, %d %B %Y"),
            day_of_week=now.strftime("%A"),
            raw_input=raw_input or normalized,
            normalized_input=normalized,
            intent=intent.name.lower() if intent else "unknown",
            conversation_history=conversation_history or [],
            mode=mode,
            is_voice=is_voice,
        )

        # Build last exchange for quick reference
        if conversation_history and len(conversation_history) >= 2:
            last_user = None
            last_assistant = None
            for msg in reversed(conversation_history):
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user" and last_user is None:
                    last_user = content
                elif role in ("assistant", "model") and last_assistant is None:
                    last_assistant = content
                if last_user and last_assistant:
                    break
            if last_user and last_assistant:
                ctx.last_exchange = f"User: {last_user}\nMJ: {last_assistant}"

        # Build capabilities prompt block
        ctx.available_capabilities = self._capability_mgr.get_capabilities_prompt_block()

        # Build tool descriptions (structured)
        ctx.tool_descriptions = self._build_tool_descriptions()

        return ctx

    def _build_tool_descriptions(self) -> list[dict]:
        """Build structured tool descriptions for the LLM."""
        descriptions = []
        for cap in self._capability_mgr.get_available_capabilities():
            desc = self._capability_mgr.get_descriptor(cap)
            if not desc:
                continue
            descriptions.append({
                "capability": desc.name,
                "description": desc.description,
                "parameters": desc.parameters if desc.parameters else None,
                "requires_internet": desc.requires_internet,
                "requires_approval": desc.requires_approval,
            })
        return descriptions

    def inject_memory(self, ctx: PipelineContext, memories: list[str]) -> PipelineContext:
        """Inject relevant memories into the context."""
        ctx.relevant_memories = memories
        return ctx

    def inject_preferences(self, ctx: PipelineContext, preferences: dict[str, Any]) -> PipelineContext:
        """Inject user preferences into the context."""
        ctx.user_preferences = preferences
        return ctx

