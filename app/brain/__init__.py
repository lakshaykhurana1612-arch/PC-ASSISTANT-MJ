"""
MJ Brain — Decision engine and planning layer.

Modules:
- groq_client: LLM client with Gemini/Groq fallback
- llm: LLM decision protocol adapter
- pdf_groq: PDF analysis via Groq
- tool_registry: Central tool/capability definitions
- capability_manager: Abstract capability interface
- input_normalizer: Input text normalization
- intent_router: Pre-LLM intent classification (regex/keyword only)
- context_builder: Context assembly for prompts
- planner: Task planner with capability-based plans
- prompt_builder: Structured prompt construction
- plan_validator: LLM output validation against ToolRegistry
- response_builder: Final response formatting for TTS
- middleware: Middleware pipeline for the Brain
"""

from app.brain.tool_registry import ToolRegistry, Capability, ToolDefinition
from app.brain.capability_manager import CapabilityManager
from app.brain.input_normalizer import InputNormalizer, NormalizedInput
from app.brain.intent_router import IntentRouter, IntentResult, IntentType
from app.brain.context_builder import ContextBuilder, PipelineContext
from app.brain.planner import Planner, Plan, Task, Step, PlanStatus
from app.brain.prompt_builder import PromptBuilder, StructuredPrompt
from app.brain.plan_validator import PlanValidator, ValidationResult
from app.brain.response_builder import ResponseBuilder, FinalResponse
from app.brain.middleware import MiddlewarePipeline, PipelineState

__all__ = [
    "ToolRegistry",
    "Capability",
    "ToolDefinition",
    "CapabilityManager",
    "InputNormalizer",
    "NormalizedInput",
    "IntentRouter",
    "IntentResult",
    "IntentType",
    "ContextBuilder",
    "PipelineContext",
    "Planner",
    "Plan",
    "Task",
    "Step",
    "PlanStatus",
    "PromptBuilder",
    "StructuredPrompt",
    "PlanValidator",
    "ValidationResult",
    "ResponseBuilder",
    "FinalResponse",
    "MiddlewarePipeline",
    "PipelineState",
]

