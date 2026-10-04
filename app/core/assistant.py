from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class InputProvider(Protocol):
    def get_input(self) -> str | None: ...


class LLMDecisionProvider(Protocol):
    def decide(self, user_input: str) -> str | None: ...


class ActionExecutor(Protocol):
    def execute(self, ai_decision: str) -> str | None: ...


@dataclass
class Assistant:
    """High-level assistant orchestrator.

    This class is currently not wired into runtime by default.
    It exists to establish a clean architecture entry point.
    """

    llm: LLMDecisionProvider
    executor: ActionExecutor

    def run(self, user_input: str) -> str | None:
        ai_decision = self.llm.decide(user_input)
        if not ai_decision:
            return None
        return self.executor.execute(ai_decision)

