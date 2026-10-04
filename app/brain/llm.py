from __future__ import annotations

from typing import Protocol

from app.brain.groq_client import analyze_command_with_ai


class LLMDecision(Protocol):
    def decide(self, user_input: str) -> str | None: ...


class GroqGeminiLLM:
    """Thin adapter over existing analyze_command_with_ai for architecture layering."""

    def decide(self, user_input: str) -> str | None:
        return analyze_command_with_ai(user_input)

