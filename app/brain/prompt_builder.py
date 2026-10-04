"""
Prompt Builder — Constructs structured LLM prompts from plan + context.

The Prompt Builder receives:
- Pipeline context (time, history, capabilities)
- Plan (structured tasks/steps)
- System prompt (MJ persona)
- User input

And produces a structured prompt for the LLM that includes:
1. System instructions (MJ persona)
2. Context block (time, date, mode, capabilities)
3. Plan structure (tasks to complete)
4. Conversation history
5. User request
6. Output format instructions

Usage:
    builder = PromptBuilder()
    prompt = builder.build(context, plan)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from app.brain.context_builder import PipelineContext
from app.brain.planner import Plan

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt Structure
# ---------------------------------------------------------------------------


@dataclass
class StructuredPrompt:
    """A fully structured prompt ready for LLM consumption."""

    system_instructions: str = ""
    context_block: str = ""
    plan_block: str = ""
    history_block: str = ""
    user_request: str = ""
    output_instructions: str = ""
    full_prompt: str = ""

    def to_dict(self) -> dict[str, str]:
        """Get prompt parts as dictionary."""
        return {
            "system": self.system_instructions,
            "context": self.context_block,
            "plan": self.plan_block,
            "history": self.history_block,
            "user": self.user_request,
            "output": self.output_instructions,
        }


# ---------------------------------------------------------------------------
# Prompt Builder
# ---------------------------------------------------------------------------


class PromptBuilder:
    """Builds structured prompts from pipeline context and plan.

    Usage:
        builder = PromptBuilder()
        prompt = builder.build(context, plan, user_input="weather in delhi")
    """

    # Default MJ system prompt (can be overridden)
    DEFAULT_SYSTEM_PROMPT = r"""You are MJ — a highly intelligent AI assistant and digital partner.

IDENTITY:
- Name: MJ
- Gender: Female | Age: ~22 | Nationality: Indian
- Languages: Hindi, English, Hinglish
- Primary Style: Natural Indian Hinglish

PERSONALITY:
- Behave like a smart Indian best friend
- Address the user as "Boss" or "Yaar" (never overuse)
- Be: Friendly, Funny, Playful, Confident, Helpful, Slightly sarcastic
- Never sound robotic, overly formal, or like customer support
- Never say "As an AI...", "I apologize for the inconvenience..."

CRITICAL RULES:
1. Never invent commands, files, apps, folders, websites, or results
2. If uncertain, say so
3. Keep responses concise — 1-2 lines for casual chat
4. Technical explanations can be detailed
5. Never break formatting — every response must follow the OUTPUT FORMAT

OUTPUT FORMAT:
Respond with a JSON object containing:
{
    "response_type": "chat" | "plan",
    "text": "your response text",
    "capabilities": ["CAPABILITY_NAME", ...],
    "parameters": {}
}

For chat/answers: use "chat" response_type
For actions: use "plan" response_type with capability names and parameters

AVAILABLE CAPABILITIES will be provided in the context.
Use ONLY the capabilities listed in AVAILABLE CAPABILITIES.
"""

    def __init__(self):
        self.system_prompt = self.DEFAULT_SYSTEM_PROMPT

    def build(
        self,
        context: PipelineContext,
        plan: Plan,
        user_input: str = "",
        conversation_history: Optional[list[dict]] = None,
    ) -> StructuredPrompt:
        """Build a complete structured prompt.

        Args:
            context: PipelineContext from ContextBuilder
            plan: Plan from Planner
            user_input: raw user input
            conversation_history: full conversation history

        Returns:
            StructuredPrompt with all parts assembled
        """
        prompt = StructuredPrompt()

        # 1. System instructions
        prompt.system_instructions = self.system_prompt

        # 2. Context block
        prompt.context_block = self._build_context_block(context)

        # 3. Plan block
        prompt.plan_block = self._build_plan_block(plan)

        # 4. History block
        prompt.history_block = self._build_history_block(conversation_history or context.conversation_history)

        # 5. User request
        prompt.user_request = user_input or context.normalized_input

        # 6. Output instructions
        prompt.output_instructions = self._build_output_instructions()

        # 7. Full prompt assembly
        prompt.full_prompt = self._assemble(prompt)

        return prompt

    def _build_context_block(self, ctx: PipelineContext) -> str:
        """Build the context information block."""
        lines = [
            "=== CONTEXT ===",
            f"Date: {ctx.current_date}",
            f"Time: {ctx.current_time}",
            f"Day: {ctx.day_of_week}",
            f"System Mode: {ctx.mode}",
            f"Voice Input: {ctx.is_voice}",
            "",
            ctx.available_capabilities,
        ]
        return "\n".join(lines)

    def _build_plan_block(self, plan: Plan) -> str:
        """Build the plan structure block."""
        if not plan or not plan.tasks:
            return "=== PLAN ===\nNo specific plan generated. Respond naturally."

        lines = ["=== PLAN ==="]
        lines.append(f"Plan ID: {plan.id}")
        lines.append(f"Intent: {plan.intent}")
        lines.append(f"Total Tasks: {len(plan.tasks)}")
        lines.append("")

        for i, task in enumerate(plan.tasks, 1):
            lines.append(f"Task {i}: {task.description}")
            lines.append(f"  Priority: {task.priority}")
            for j, step in enumerate(task.steps, 1):
                lines.append(f"  Step {j}: [{step.capability}] {step.description}")
                if step.parameters:
                    lines.append(f"    Params: {json.dumps(step.parameters)}")
            lines.append("")

        return "\n".join(lines)

    def _build_history_block(self, history: list[dict]) -> str:
        """Build conversation history block."""
        if not history:
            return "=== CONVERSATION HISTORY ===\n(No recent conversation)"

        lines = ["=== CONVERSATION HISTORY ==="]
        for msg in history[-8:]:  # Last 8 messages for context
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            # Truncate long content
            if isinstance(content, str) and len(content) > 300:
                content = content[:300] + "..."
            lines.append(f"[{role}]: {content}")

        return "\n".join(lines)

    def _build_output_instructions(self) -> str:
        """Build output format instructions."""
        return """=== OUTPUT FORMAT ===
Respond with a JSON object:
{
    "response_type": "chat" | "plan",
    "text": "your response to Boss in Hinglish",
    "capabilities": ["LIST", "OF", "CAPABILITIES", "TO", "EXECUTE"],
    "parameters": {},
    "plan_summary": "brief summary of what you'll do"
}

RULES:
- response_type "chat": Pure conversation, no actions needed
- response_type "plan": Actions required — list capabilities to execute
- Use ONLY capabilities listed in AVAILABLE CAPABILITIES
- NEVER invent capabilities or tools
- text must be in Hinglish (mix Hindi + English), natural tone
- Keep text concise unless technical explanation is needed
- If the user's request is unclear, ask for clarification via text"""

    def _assemble(self, prompt: StructuredPrompt) -> str:
        """Assemble all parts into the full prompt."""
        parts = [
            prompt.system_instructions,
            "",
            prompt.context_block,
            "",
            prompt.history_block,
            "",
            prompt.plan_block,
            "",
            f"=== USER REQUEST ===\n{prompt.user_request}",
            "",
            prompt.output_instructions,
        ]
        return "\n".join(parts)

    def set_system_prompt(self, custom_prompt: str) -> None:
        """Override the default system prompt."""
        self.system_prompt = custom_prompt

    def build_mlx_prompt(
        self,
        context: PipelineContext,
        plan: Plan,
        user_input: str,
    ) -> list[dict]:
        """Build a prompt suitable for MLX/Groq chat format.

        Returns a list of message dicts with role/content.
        """
        messages = []

        # System message
        system_content = self.system_prompt + "\n\n" + context.as_prompt_block()
        messages.append({"role": "system", "content": system_content})

        # Conversation history
        for msg in context.conversation_history[-6:]:
            role = msg.get("role", "user")
            if role == "model":
                role = "assistant"
            content = msg.get("content", "")
            messages.append({"role": role, "content": content})

        # Plan context
        plan_text = self._build_plan_block(plan)
        if plan_text:
            messages.append({"role": "system", "content": plan_text})

        # User request
        messages.append({"role": "user", "content": user_input})

        return messages

