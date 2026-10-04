from __future__ import annotations

"""Core router/orchestrator.

This router is additive: it does not replace existing main.py logic yet.
It provides a single place to unify flows in future migrations.
"""

from dataclasses import dataclass

from app.core.assistant import Assistant


@dataclass
class Router:
    assistant: Assistant

    def handle_user_input(self, user_input: str) -> str | None:
        return self.assistant.run(user_input)

