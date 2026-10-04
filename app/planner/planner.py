"""
Pipeline Orchestrator — High-level orchestrator for the Brain middleware pipeline.

Coordinates the full pipeline:
    User Input → Pipeline → Validated Plan → Executor → Response

This is the main entry point for all user input processing.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from app.brain.middleware import MiddlewarePipeline, PipelineState
from app.brain.response_builder import FinalResponse
from app.planner.executor import PlanExecutor
from app.events.event_bus import get_event_bus
from app.events.events import PipelineEvent, ErrorEvent

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """High-level orchestrator for the Brain pipeline.

    Manages the full lifecycle:
    1. Create and configure the middleware pipeline
    2. Run user input through the pipeline
    3. Execute validated plans
    4. Return final response

    This is the MAIN ENTRY POINT for processing user input.
    Existing code paths (execute_smart_action, analyze_command_with_ai)
    remain UNCHANGED and fully backward compatible.

    Usage:
        orchestrator = PipelineOrchestrator()
        response = orchestrator.process("send resume to rahul on whatsapp")
        speak(response.speech_text)
    """

    def __init__(
        self,
        llm_callback: Optional[Callable[[str], str]] = None,
        system_prompt: Optional[str] = None,
    ):
        self._pipeline = MiddlewarePipeline()
        self._executor = PlanExecutor()
        self._event_bus = get_event_bus()

        # Override LLM callback if provided
        self._llm_callback = llm_callback

        if system_prompt:
            self._pipeline.set_system_prompt(system_prompt)

        # Pipeline state for debugging
        self._last_state: Optional[PipelineState] = None

    # ------------------------------------------------------------------
    # Main processing
    # ------------------------------------------------------------------

    def process(
        self,
        user_input: str,
        conversation_history: Optional[list[dict]] = None,
        mode: str = "classic",
        is_voice: bool = False,
        execute_plan: bool = True,
    ) -> FinalResponse:
        """Process user input through the full pipeline.

        Args:
            user_input: raw user input
            conversation_history: recent conversation messages
            mode: current system mode
            is_voice: whether input is from voice
            execute_plan: whether to execute the plan (True) or just validate (False)

        Returns:
            FinalResponse ready for TTS/output
        """
        # Run through pipeline
        response = self._pipeline.run(
            user_input=user_input,
            llm_callback=self._llm_callback,
            conversation_history=conversation_history,
            mode=mode,
            is_voice=is_voice,
        )

        # Store last state
        self._last_state = self._pipeline  # Accessible via debug

        # Execute plan if needed
        if execute_plan and response and not response.is_system_command:
            execution_result = self._execute_plan_from_response(response)
            if execution_result:
                response.speech_text = execution_result.get("speech", response.speech_text)
                response.display_text = execution_result.get("display", response.display_text)

        self._event_bus.publish(PipelineEvent(
            stage="complete",
            data={
                "speech": response.speech_text if response else "",
                "is_system": response.is_system_command if response else False,
            },
        ))

        return response

    def _execute_plan_from_response(self, response: FinalResponse) -> Optional[dict]:
        """Execute capabilities from the validated response.

        Extracts capability names from the validation result and executes them
        through the PlanExecutor.

        Args:
            response: FinalResponse containing validation result

        Returns:
            Optional dict with execution results
        """
        if not response or not hasattr(response, 'raw_llm_output'):
            return None

        # Get validation result from pipeline state
        # The PlanExecutor can parse capabilities from the raw LLM output
        return self._executor.execute_from_llm_output(response.raw_llm_output)

    # ------------------------------------------------------------------
    # Quick processing (bypass pipeline for simple commands)
    # ------------------------------------------------------------------

    def quick_chat(self, user_input: str) -> str:
        """Quick chat processing — bypasses planning and validation.

        Useful for simple chat responses where no automation is needed.

        Args:
            user_input: user message

        Returns:
            speech text response
        """
        self._pipeline.skip_planning = True
        self._pipeline.skip_validation = True

        response = self._pipeline.run(
            user_input=user_input,
            llm_callback=self._llm_callback,
        )

        # Reset flags
        self._pipeline.skip_planning = False
        self._pipeline.skip_validation = False

        return response.speech_text if response else ""

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_llm_callback(self, callback: Callable[[str], str]) -> None:
        """Override the LLM callback."""
        self._llm_callback = callback

    def add_pre_middleware(self, middleware) -> None:
        """Add a pre-processing middleware."""
        self._pipeline.add_pre_middleware(middleware)

    def add_post_middleware(self, middleware) -> None:
        """Add a post-processing middleware."""
        self._pipeline.add_post_middleware(middleware)

    def summary(self) -> dict[str, Any]:
        """Get orchestrator summary."""
        return {
            "pipeline": self._pipeline.summary(),
            "has_llm_callback": self._llm_callback is not None,
        }

