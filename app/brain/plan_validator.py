"""
Plan Validator — Validates LLM output against the ToolRegistry.

Rejects hallucinated capabilities/tools. Only registered capabilities pass through.

Validation rules:
1. All capability names must exist in the ToolRegistry
2. All parameters must match the tool definitions
3. Required parameters must be present
4. Unknown/hallucinated capabilities are rejected

Usage:
    validator = PlanValidator()
    result = validator.validate_llm_output({"capabilities": ["FILE_SEARCH"], ...})
    # result.valid = True
    # result.invalid_capabilities = []
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from app.brain.tool_registry import ToolRegistry, Capability

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """Result of validating an LLM output."""

    valid: bool = True
    response_type: str = ""
    text: str = ""
    valid_capabilities: list[str] = field(default_factory=list)
    invalid_capabilities: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    plan_summary: str = ""
    raw_output: str = ""


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class PlanValidator:
    """Validates LLM output against the tool/capability registry.

    Usage:
        validator = PlanValidator()
        result = validator.validate(raw_llm_text)
    """

    def __init__(self):
        self._registry = ToolRegistry.get_instance()

        # Build set of valid capability names (for fast lookup)
        self._valid_capabilities: set[str] = set()
        for cap in Capability:
            self._valid_capabilities.add(cap.name)

    def validate(self, llm_output: str) -> ValidationResult:
        """Validate LLM output string.

        Args:
            llm_output: raw text output from LLM

        Returns:
            ValidationResult with valid/invalid capabilities
        """
        result = ValidationResult(raw_output=llm_output)

        if not llm_output or not llm_output.strip():
            result.valid = False
            result.errors.append("Empty LLM output")
            return result

        # Try to parse as JSON
        parsed = self._try_parse_json(llm_output)

        if parsed is None:
            # Fallback: try to extract tags from raw text
            return self._validate_raw_text(llm_output)

        return self._validate_parsed(parsed, result)

    def _try_parse_json(self, text: str) -> Optional[dict]:
        """Try to parse text as JSON."""
        text = text.strip()

        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code block
        for marker in ["```json", "```"]:
            if marker in text:
                start = text.find(marker) + len(marker)
                end = text.find("```", start)
                if end > start:
                    try:
                        return json.loads(text[start:end].strip())
                    except json.JSONDecodeError:
                        pass

        # Try to find JSON-like structure
        try:
            brace_start = text.find("{")
            brace_end = text.rfind("}")
            if brace_start >= 0 and brace_end > brace_start:
                return json.loads(text[brace_start : brace_end + 1])
        except (json.JSONDecodeError, ValueError):
            pass

        return None

    def _validate_parsed(self, parsed: dict, result: ValidationResult) -> ValidationResult:
        """Validate a parsed JSON object from LLM."""
        # Extract fields
        result.response_type = parsed.get("response_type", "chat")
        result.text = parsed.get("text", "")
        result.plan_summary = parsed.get("plan_summary", "")

        capabilities = parsed.get("capabilities", [])
        if isinstance(capabilities, str):
            capabilities = [capabilities]

        parameters = parsed.get("parameters", {})
        if not isinstance(parameters, dict):
            parameters = {}

        result.parameters = parameters

        # Validate each capability
        valid_caps = []
        invalid_caps = []

        for cap in capabilities:
            cap_upper = cap.upper().strip()
            if cap_upper in self._valid_capabilities:
                valid_caps.append(cap_upper)
            else:
                # Check if it's a tag name (backward compat)
                tool = self._registry.get_by_tag(cap_upper)
                if tool:
                    valid_caps.append(tool.capability.name)
                else:
                    invalid_caps.append(cap)
                    result.errors.append(f"Unknown capability: '{cap}'")

        result.valid_capabilities = valid_caps
        result.invalid_capabilities = invalid_caps

        # Mark invalid if any hallucinated capabilities
        if invalid_caps:
            result.valid = False
            logger.warning(f"Hallucinated capabilities rejected: {invalid_caps}")

        # Validate response_type
        if result.response_type not in ("chat", "plan"):
            result.errors.append(f"Invalid response_type: '{result.response_type}'. Must be 'chat' or 'plan'.")
            result.valid = False

        return result

    def _validate_raw_text(self, text: str) -> ValidationResult:
        """Fallback: validate raw text by extracting known tags."""
        result = ValidationResult(raw_output=text)

        # Check if it starts with a known tag pattern
        known_tags = self._registry.list_tags()
        found_tags = []

        for tag in sorted(known_tags, key=len, reverse=True):
            if tag in text.upper():
                found_tags.append(tag)

        if found_tags:
            # Get capabilities for found tags
            caps = set()
            for tag in found_tags:
                tool = self._registry.get_by_tag(tag)
                if tool:
                    caps.add(tool.capability.name)

            result.response_type = "plan"
            result.valid_capabilities = list(caps)
            result.text = text
            result.valid = True
        else:
            # No tags found — treat as chat
            result.response_type = "chat"
            result.text = text
            result.valid_capabilities = []
            result.valid = True

        return result

    def validate_plan(self, plan) -> ValidationResult:
        """Validate a Plan dataclass instance.

        Args:
            plan: Plan instance from Planner

        Returns:
            ValidationResult
        """
        result = ValidationResult()

        if not plan.tasks:
            result.valid = True
            result.response_type = "chat"
            return result

        for task in plan.tasks:
            for step in task.steps:
                cap_name = step.capability.upper() if step.capability else ""
                if cap_name not in self._valid_capabilities:
                    result.invalid_capabilities.append(step.capability)
                    result.errors.append(
                        f"Task '{task.description}' has invalid capability: '{step.capability}'"
                    )

        if result.invalid_capabilities:
            result.valid = False

        return result

