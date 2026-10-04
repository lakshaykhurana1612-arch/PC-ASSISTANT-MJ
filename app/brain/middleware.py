"""
Middleware Pipeline — Processing chain for the Brain.

Each middleware component processes the input/output in sequence:

    Input → Normalizer → Intent Router → Context Builder → Planner
    → Prompt Builder → LLM → Validator → Response Builder → Output

Middlewares are modular and can be enabled/disabled independently.
The pipeline supports pre-processing (before LLM) and post-processing (after LLM).

Usage:
    pipeline = MiddlewarePipeline()
    result = pipeline.run("send resume to rahul on whatsapp")
    # result is a FinalResponse ready for TTS/output
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.brain.input_normalizer import InputNormalizer, NormalizedInput
from app.brain.intent_router import IntentRouter, IntentResult, IntentType
from app.brain.context_builder import ContextBuilder, PipelineContext
from app.brain.planner import Planner, Plan
from app.brain.prompt_builder import PromptBuilder, StructuredPrompt
from app.brain.plan_validator import PlanValidator, ValidationResult
from app.brain.response_builder import ResponseBuilder, FinalResponse
from app.events.event_bus import get_event_bus
from app.events.events import (
    PipelineEvent,
    IntentEvent,
    PlanEvent,
    ExecutionEvent,
    ResponseEvent,
    ErrorEvent,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Middleware types
# ---------------------------------------------------------------------------

PreMiddleware = Callable[[str], str]
PostMiddleware = Callable[[FinalResponse], FinalResponse]
PipelineHook = Callable[[dict[str, Any]], None]


# ---------------------------------------------------------------------------
# Pipeline state
# ---------------------------------------------------------------------------


@dataclass
class PipelineState:
    """Accumulated state through the pipeline."""

    raw_input: str = ""
    normalized: NormalizedInput | None = None
    intent: IntentResult | None = None
    context: PipelineContext | None = None
    plan: Plan | None = None
    prompt: StructuredPrompt | None = None
    llm_output: str = ""
    validation: ValidationResult | None = None
    response: FinalResponse | None = None
    errors: list[str] = field(default_factory=list)
    timeline: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Middleware Pipeline
# ---------------------------------------------------------------------------


class MiddlewarePipeline:
    """Configurable middleware pipeline for the Brain.

    Processes user input through a chain of middleware components:
    1. Pre-middlewares (modify input before routing)
    2. Pipeline stages (normalize → route → context → plan → prompt → LLM → validate → respond)
    3. Post-middlewares (modify output after generation)

    Usage:
        pipeline = MiddlewarePipeline()
        pipeline.add_pre_middleware(my_normalizer)
        pipeline.add_post_middleware(my_formatter)
        result = pipeline.run("hello boss")
    """

    def __init__(self):
        # Core components
        self.normalizer = InputNormalizer()
        self.intent_router = IntentRouter()
        self.context_builder = ContextBuilder()
        self.planner = Planner()
        self.prompt_builder = PromptBuilder()
        self.validator = PlanValidator()
        self.response_builder = ResponseBuilder()

        # Middleware hooks
        self._pre_middlewares: list[PreMiddleware] = []
        self._post_middlewares: list[PostMiddleware] = []
        self._hooks: list[PipelineHook] = []

        # Event bus
        self._event_bus = get_event_bus()

        # Pipeline config
        self.skip_intent_routing = False
        self.skip_planning = False
        self.skip_validation = False

    # ------------------------------------------------------------------
    # Middleware registration
    # ------------------------------------------------------------------

    def add_pre_middleware(self, middleware: PreMiddleware) -> None:
        """Add a pre-processing middleware (runs before intent routing).

        Args:
            middleware: callable that takes input string, returns modified string
        """
        self._pre_middlewares.append(middleware)

    def add_post_middleware(self, middleware: PostMiddleware) -> None:
        """Add a post-processing middleware (runs after response generation).

        Args:
            middleware: callable that takes FinalResponse, returns modified FinalResponse
        """
        self._post_middlewares.append(middleware)

    def add_hook(self, hook: PipelineHook) -> None:
        """Add a pipeline hook (called after each stage with full state).

        Args:
            hook: callable that takes PipelineState
        """
        self._hooks.append(hook)

    # ------------------------------------------------------------------
    # Pipeline execution
    # ------------------------------------------------------------------

    def run(
        self,
        user_input: str,
        llm_callback: Optional[Callable[[str], str]] = None,
        conversation_history: Optional[list[dict]] = None,
        mode: str = "classic",
        is_voice: bool = False,
    ) -> FinalResponse:
        """Run the full middleware pipeline.

        Args:
            user_input: raw user input
            llm_callback: function to call LLM (takes prompt string, returns response)
            conversation_history: recent conversation messages
            mode: current system mode
            is_voice: whether input is from voice

        Returns:
            FinalResponse ready for output
        """
        state = PipelineState(raw_input=user_input)
        start_time = time.time()

        try:
            # ==========================================================
            # 1. PRE-MIDDLEWARES
            # ==========================================================
            processed_input = user_input
            for mw in self._pre_middlewares:
                try:
                    processed_input = mw(processed_input)
                except Exception as e:
                    logger.warning(f"Pre-middleware error: {e}")

            state.raw_input = processed_input
            state.timeline["pre_middleware"] = time.time()

            # ==========================================================
            # 2. INPUT NORMALIZATION
            # ==========================================================
            state.normalized = self.normalizer.normalize(processed_input)
            state.timeline["normalize"] = time.time()

            if state.normalized.is_empty:
                return self._empty_input_response()

            self._emit(PipelineEvent("normalize", state.normalized.original))
            self._notify_hooks(state)

            # ==========================================================
            # 3. INTENT ROUTING
            # ==========================================================
            if not self.skip_intent_routing:
                state.intent = self.intent_router.classify(state.normalized.clean_text)
            else:
                state.intent = IntentResult(intent=IntentType.UNKNOWN)

            state.timeline["route"] = time.time()

            self._emit(IntentEvent(
                intent=state.intent.intent.name.lower() if state.intent else "unknown",
                data={"confidence": state.intent.confidence if state.intent else 0},
            ))
            self._notify_hooks(state)

            # ==========================================================
            # 4. CONTEXT BUILDING
            # ==========================================================
            state.context = self.context_builder.build(
                normalized=state.normalized.clean_text,
                intent=state.intent.intent if state.intent else IntentType.UNKNOWN,
                raw_input=state.normalized.original,
                conversation_history=conversation_history,
                mode=mode,
                is_voice=is_voice,
            )
            state.timeline["context"] = time.time()

            self._emit(PipelineEvent("context", state.context.normalized_input))
            self._notify_hooks(state)

            # ==========================================================
            # 5. PLANNING
            # ==========================================================
            if not self.skip_planning:
                state.plan = self.planner.create_plan(
                    normalized_input=state.normalized.clean_text,
                    intent=state.intent.intent if state.intent else IntentType.UNKNOWN,
                )
            else:
                state.plan = Plan(
                    user_input=state.normalized.clean_text,
                    intent="unknown",
                )

            state.timeline["plan"] = time.time()

            self._emit(PlanEvent(
                status="created",
                data={
                    "plan_id": state.plan.id if state.plan else "",
                    "task_count": len(state.plan.tasks) if state.plan and state.plan.tasks else 0,
                },
            ))
            self._notify_hooks(state)

            # ==========================================================
            # 6. PROMPT BUILDING
            # ==========================================================
            state.prompt = self.prompt_builder.build(
                context=state.context,
                plan=state.plan,
                user_input=state.normalized.clean_text,
                conversation_history=conversation_history,
            )
            state.timeline["prompt"] = time.time()

            self._emit(PipelineEvent("prompt", data={"prompt_length": len(state.prompt.full_prompt)}))
            self._notify_hooks(state)

            # ==========================================================
            # 7. LLM CALL
            # ==========================================================
            if llm_callback:
                state.llm_output = llm_callback(state.prompt.full_prompt)
            else:
                # Default: use existing groq_client
                state.llm_output = self._default_llm_call(state.prompt.full_prompt)

            state.timeline["llm"] = time.time()

            self._emit(PipelineEvent("llm", data={"output_length": len(state.llm_output)}))
            self._notify_hooks(state)

            # ==========================================================
            # 8. PLAN VALIDATION
            # ==========================================================
            if not self.skip_validation:
                state.validation = self.validator.validate(state.llm_output)
            else:
                state.validation = ValidationResult(
                    valid=True,
                    text=state.llm_output,
                )

            state.timeline["validate"] = time.time()

            if state.validation and not state.validation.valid:
                self._emit(ErrorEvent(
                    error_type="validation",
                    data=state.validation.errors,
                ))
                logger.warning(f"Validation errors: {state.validation.errors}")

            self._notify_hooks(state)

            # ==========================================================
            # 9. RESPONSE BUILDING
            # ==========================================================
            state.response = self.response_builder.build(
                validation_result=state.validation,
                context=state.context,
            )
            state.timeline["respond"] = time.time()

            self._emit(ResponseEvent(
                text=state.response.speech_text,
                data=state.response.to_dict(),
            ))

            # ==========================================================
            # 10. POST-MIDDLEWARES
            # ==========================================================
            for mw in self._post_middlewares:
                try:
                    state.response = mw(state.response)
                except Exception as e:
                    logger.warning(f"Post-middleware error: {e}")

            state.timeline["post_middleware"] = time.time()

            # Calculate total duration
            total_ms = (time.time() - start_time) * 1000
            logger.info(f"Pipeline completed in {total_ms:.1f}ms")

            self._notify_hooks(state)

            return state.response

        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            self._emit(ErrorEvent(
                error_type="pipeline",
                message=str(e),
                recoverable=True,
            ))
            return FinalResponse(
                speech_text="Sorry Boss, pipeline mein error aa gaya. Lekin main purane tareeke se kaam kar rahi hoon!",
                display_text=f"Pipeline Error: {e}",
                error=str(e),
            )

    # ------------------------------------------------------------------
    # Default LLM call
    # ------------------------------------------------------------------

    def _default_llm_call(self, prompt: str) -> str:
        """Default LLM call using groq_client.

        This can be overridden by passing llm_callback to run().
        """
        try:
            from app.brain.groq_client import analyze_command_with_ai
            return analyze_command_with_ai(prompt)
        except Exception as e:
            logger.error(f"Default LLM call failed: {e}")
            return "CHAT: Sorry Boss, LLM se response nahi mila."

    # ------------------------------------------------------------------
    # Empty input handling
    # ------------------------------------------------------------------

    def _empty_input_response(self) -> FinalResponse:
        """Return a response for empty input."""
        return FinalResponse(
            speech_text="",
            display_text="",
            has_speech=False,
            error="Empty input",
        )

    # ------------------------------------------------------------------
    # Event emission & hooks
    # ------------------------------------------------------------------

    def _emit(self, event) -> None:
        """Emit an event to the event bus."""
        try:
            self._event_bus.publish(event)
        except Exception as e:
            logger.warning(f"Event publish error: {e}")

    def _notify_hooks(self, state: PipelineState) -> None:
        """Notify all registered hooks with current state."""
        for hook in self._hooks:
            try:
                hook(state)
            except Exception as e:
                logger.warning(f"Hook error: {e}")

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_system_prompt(self, prompt: str) -> None:
        """Override the default system prompt."""
        self.prompt_builder.set_system_prompt(prompt)

    def summary(self) -> dict[str, Any]:
        """Get pipeline summary for debugging."""
        return {
            "pre_middlewares": len(self._pre_middlewares),
            "post_middlewares": len(self._post_middlewares),
            "hooks": len(self._hooks),
            "skip_intent_routing": self.skip_intent_routing,
            "skip_planning": self.skip_planning,
            "skip_validation": self.skip_validation,
        }

