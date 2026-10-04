from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.utils.actions import execute_smart_action
from app.planner.executor import PlanExecutor


@dataclass
class TagExecutor:
    """Adapter over existing execute_smart_action and new PlanExecutor.

    Provides backward compatibility while also supporting the new
    capability-based Plan execution.

    Usage:
        # Old way (backward compatible)
        executor = TagExecutor()
        result = executor.execute(ai_decision)

        # New way
        plan_result = executor.execute_plan(llm_json_output)
    """

    def execute(self, ai_decision: str) -> str | None:
        """Legacy execution: parse AI decision tags and execute.

        Args:
            ai_decision: AI decision string with tags (e.g., "FILE_SEARCH: resume.pdf && CHAT: Done")

        Returns:
            response string or None
        """
        return execute_smart_action(ai_decision)

    def execute_plan(self, llm_output: str) -> Optional[dict]:
        """Execute capabilities from LLM JSON output.

        Args:
            llm_output: LLM output with JSON capabilities

        Returns:
            dict with execution results
        """
        executor = PlanExecutor()
        return executor.execute_from_llm_output(llm_output)

    def execute_capability(self, capability_name: str, **params) -> Optional[dict]:
        """Execute a single capability.

        Args:
            capability_name: Capability enum name
            params: capability parameters

        Returns:
            dict with execution result
        """
        executor = PlanExecutor()
        return executor.execute_capability(capability_name, params)

