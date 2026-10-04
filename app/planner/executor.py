"""
Plan Executor — Translates abstract capabilities into concrete tool calls.

This is the ONLY layer that maps Capability enum values to concrete
tool tags and calls execute_smart_action(). All other layers work
with abstract capabilities only.

Rules:
1. NEVER import or reference concrete tags except in this file
2. All capability-to-tag mapping happens here
3. Always fall back to execute_smart_action() for execution
4. Never duplicate automation logic

Usage:
    executor = PlanExecutor()
    result = executor.execute_capability("FILE_SEARCH", {"query": "resume.pdf"})
    result = executor.execute_from_llm_output(llm_json_string)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.brain.tool_registry import ToolRegistry, Capability

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Execution Result
# ---------------------------------------------------------------------------


@dataclass
class ExecutionResult:
    """Result of executing a plan or capability."""

    success: bool = True
    speech: str = ""
    display: str = ""
    results: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Capability → Tag mapping
# ---------------------------------------------------------------------------

# Maps Capability enum names to concrete tag prefixes + handler logic
# The executor iterates these and generates the appropriate tag string
# for execute_smart_action()

_CAPABILITY_TO_TAGS: dict[str, dict[str, Any]] = {
    "WEB_SEARCH": {
        "tags": ["SEARCH"],
        "param_name": "query",
    },
    "FILE_SEARCH": {
        "tags": ["FILE_SEARCH"],
        "param_name": "query",
    },
    "FILE_READ": {
        "tags": ["FILE_READ"],
        "param_name": "filename",  # Special: needs question too
    },
    "FILE_MOVE": {
        "tags": ["FILE_MOVE"],
        "param_name": "request",
    },
    "FILE_DELETE": {
        "tags": ["FILE_DELETE"],
        "param_name": "request",
    },
    "WHATSAPP_MESSAGE": {
        "tags": ["WHATSAPP_MSG"],
        "param_name": "request",
    },
    "WHATSAPP_FILE": {
        "tags": ["WHATSAPP_FILE"],
        "param_name": "request",
    },
    "WHATSAPP_BACKGROUND": {
        "tags": ["BG_WHATSAPP_MSG"],
        "param_name": "request",
    },
    "WEB_BROWSER": {
        "tags": ["OPEN_WEBSITE"],  # Fallback; suggested_tags can override
        "param_name": "request",
    },
    "SYSTEM_CONTROL": {
        "tags": [],  # Handled specially
        "param_name": "",
    },
    "APP_LAUNCH": {
        "tags": ["OPEN_APPLICATION"],
        "param_name": "request",
    },
    "TAB_MANAGE": {
        "tags": ["CLOSE_TAB"],
        "param_name": "request",
    },
    "PROJECT_ANALYZE": {
        "tags": ["ANALYZE_PROJECT"],
        "param_name": "",
    },
    "FUNCTION_FIND": {
        "tags": ["FIND_FUNCTION"],
        "param_name": "request",
    },
    "SCREEN_CAPTURE": {
        "tags": [],  # Future
        "param_name": "request",
    },
    "MODE_SWITCH": {
        "tags": [],  # Handled by main.py's system command handler
        "param_name": "request",
    },
    "BACKGROUND_BROWSER": {
        "tags": ["STOP_BACKGROUND_BROWSER"],
        "param_name": "",
    },
    "CHAT": {
        "tags": [],  # No action needed
        "param_name": "",
    },

    # AI Chat platforms
    "AI_CHAT": {
        "tags": ["OPEN_CHATGPT"],  # Default to ChatGPT; tag will be overridden by parameters
        "param_name": "query",
    },
    "AI_CHAT_NEW": {
        "tags": ["OPEN_CHATGPT_NEW"],  # Force new tab
        "param_name": "query",
    },
}


# ---------------------------------------------------------------------------
# Plan Executor
# ---------------------------------------------------------------------------


class PlanExecutor:
    """Executes plans by translating capabilities to concrete tool calls.

    This is the ONLY layer that knows about concrete tags like FILE_SEARCH,
    OPEN_WEBSITE, etc. All other layers work with abstract capabilities.

    The executor calls execute_smart_action() for all automation.
    No automation logic is duplicated here.
    """

    def __init__(self):
        self._registry = ToolRegistry.get_instance()

    # ------------------------------------------------------------------
    # Execute from LLM output
    # ------------------------------------------------------------------

    def execute_from_llm_output(self, llm_output: str) -> Optional[dict]:
        """Execute capabilities from LLM JSON output.

        Parses the LLM output, extracts capabilities, and executes them.

        Args:
            llm_output: raw LLM output (JSON or tag-based text)

        Returns:
            dict with execution results or None
        """
        if not llm_output or not llm_output.strip():
            return None

        # Try to parse as JSON
        parsed = self._try_parse_json(llm_output)
        if parsed:
            capabilities = parsed.get("capabilities", [])
            parameters = parsed.get("parameters", {})
            text = parsed.get("text", "")

            results = []
            for cap in capabilities:
                result = self.execute_capability(cap, parameters)
                if result:
                    results.append(result)

            # Build combined response
            speech_parts = [text] if text else []
            display_parts = []

            for r in results:
                if r.get("speech"):
                    speech_parts.append(r["speech"])
                if r.get("display"):
                    display_parts.append(r["display"])

            return {
                "speech": " ".join(speech_parts) if speech_parts else "",
                "display": "\n".join(display_parts) if display_parts else "",
                "results": results,
            }

        # Fallback: extract tags directly from text
        return self._execute_from_tags(llm_output)

    def execute_capability(self, capability_name: str, parameters: dict) -> Optional[dict]:
        """Execute a single capability.

        Args:
            capability_name: Capability enum name (e.g., "FILE_SEARCH")
            parameters: dict of parameters

        Returns:
            dict with result info or None
        """
        cap_upper = capability_name.upper().strip()

        # Validate capability
        if not self._registry.validate_capability_name(cap_upper):
            logger.warning(f"Unknown capability: {cap_upper}")
            return None

        mapping = _CAPABILITY_TO_TAGS.get(cap_upper)
        if not mapping:
            logger.warning(f"No tag mapping for capability: {cap_upper}")
            return None

        tags = mapping["tags"]
        param_name = mapping["param_name"]

        if not tags:
            # No concrete tag needed (e.g., CHAT, MODE_SWITCH)
            logger.debug(f"Capability {cap_upper} requires no concrete tag execution")
            return {"capability": cap_upper, "status": "no_action_needed"}

        # Build the tag string for execute_smart_action
        tag = tags[0]
        if param_name and param_name in parameters:
            tag_string = f"{tag}: {parameters[param_name]}"
        elif param_name and "request" in parameters:
            tag_string = f"{tag}: {parameters['request']}"
        elif param_name and "query" in parameters:
            tag_string = f"{tag}: {parameters['query']}"
        else:
            tag_string = tag  # No parameters needed

        # Execute via existing function
        return self._call_executor(cap_upper, tag_string)

    # ------------------------------------------------------------------
    # Tag-based execution fallback
    # ------------------------------------------------------------------

    def _execute_from_tags(self, text: str) -> Optional[dict]:
        """Extract and execute tags directly from text.

        This provides backward compatibility with the old tag-based format.
        """
        if not text:
            return None

        # Check for known tags
        found_tags = self._extract_tags(text)
        if not found_tags:
            # Extract CHAT content if present
            chat_match = re.search(r"CHAT:\s*(.*?)(?:\s*&&|$)", text, re.DOTALL)
            if chat_match:
                return {
                    "speech": chat_match.group(1).strip(),
                    "display": chat_match.group(1).strip(),
                }
            return None

        # Build tag string for executor
        tag_strings = []
        for tag, value in found_tags:
            if value:
                tag_strings.append(f"{tag}: {value}")
            else:
                tag_strings.append(tag)

        combined = " && ".join(tag_strings)

        # Call executor
        return self._call_executor("MULTI", combined)

    @staticmethod
    def _extract_tags(text: str) -> list[tuple[str, str]]:
        """Extract known tags and their values from text."""
        # Known tags in priority order
        known_tags = [
            "CHAT", "SEARCH", "FILE_SEARCH", "FILE_MOVE", "FILE_DELETE",
            "FILE_READ", "OPEN_WEBSITE", "BRAVE_WEBSITE", "YOUTUBE",
            "YOUTUBE_SEARCH", "BRAVE_YOUTUBE", "WHATSAPP_MSG",
            "WHATSAPP_FILE", "BG_WHATSAPP_MSG", "BG_WHATSAPP_FILE",
            "CLOSE_TAB", "CLOSE_SPECIFIC_TABS", "RESTART_SYSTEM",
            "SHUTDOWN_SYSTEM", "ANALYZE_PROJECT", "FIND_FUNCTION",
            "OPEN_APPLICATION", "DUPLEX_MODE", "STOP_BACKGROUND_BROWSER",
            "OPEN_CHATGPT", "OPEN_GEMINI", "OPEN_CHATAI",
            "OPEN_CHATGPT_NEW", "OPEN_GEMINI_NEW",
        ]

        found = []
        text_upper = text.upper()

        for tag in known_tags:
            # Try to find tag with value
            pattern = rf"{tag}:\s*(.*?)(?:\s*&&|\s*$|(?=\s+(?:{'|'.join(known_tags)})))"
            match = re.search(pattern, text, re.DOTALL)
            if match:
                found.append((tag, match.group(1).strip()))
            elif tag in text_upper:
                found.append((tag, ""))

        return found

    # ------------------------------------------------------------------
    # Core executor call
    # ------------------------------------------------------------------

    @staticmethod
    def _call_executor(capability: str, tag_string: str) -> Optional[dict]:
        """Call execute_smart_action with the built tag string.

        This is the ONLY place where execute_smart_action is called
        from the new pipeline. No other new code calls it directly.
        """
        try:
            from app.utils.actions import execute_smart_action

            result = execute_smart_action(tag_string)

            return {
                "capability": capability,
                "tag_string": tag_string,
                "status": "completed" if result is not None else "completed_no_result",
                "speech": result if isinstance(result, str) else "",
                "display": result if isinstance(result, str) else "",
            }
        except Exception as e:
            logger.error(f"Executor error for {capability}: {e}")
            return {
                "capability": capability,
                "tag_string": tag_string,
                "status": "failed",
                "error": str(e),
            }

    # ------------------------------------------------------------------
    # JSON parsing helper
    # ------------------------------------------------------------------

    @staticmethod
    def _try_parse_json(text: str) -> Optional[dict]:
        """Try to parse text as JSON, with fallback extraction."""
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try markdown code block
        for marker in ["```json", "```"]:
            if marker in text:
                start = text.find(marker) + len(marker)
                end = text.find("```", start)
                if end > start:
                    try:
                        return json.loads(text[start:end].strip())
                    except json.JSONDecodeError:
                        pass

        # Try to find JSON object
        try:
            brace_start = text.find("{")
            brace_end = text.rfind("}")
            if brace_start >= 0 and brace_end > brace_start:
                return json.loads(text[brace_start : brace_end + 1])
        except (json.JSONDecodeError, ValueError):
            pass

        return None


# ---------------------------------------------------------------------------
# Quick execution helpers (for backward compatibility)
# ---------------------------------------------------------------------------


def execute_capability(capability_name: str, **params) -> Optional[dict]:
    """Quick helper to execute a single capability.

    Usage:
        result = execute_capability("FILE_SEARCH", query="resume.pdf")
    """
    executor = PlanExecutor()
    return executor.execute_capability(capability_name, params)

