"""
Response Builder — Formats the final output for TTS or text display.

Takes the validated LLM response and conversation state, then builds
the appropriate output:
- TTS-ready speech text (Hinglish, cleaned)
- Text response for display
- System commands (mode switches, etc.)
- Error messages

Usage:
    builder = ResponseBuilder()
    response = builder.build(validation_result, context)
    # response.speech_text -> "Done Boss, file mil gayi!"
    # response.display_text -> "✅ File found at D:/docs/report.pdf"
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.brain.plan_validator import ValidationResult
from app.brain.context_builder import PipelineContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response types
# ---------------------------------------------------------------------------


@dataclass
class FinalResponse:
    """The final response ready for output."""

    speech_text: str = ""  # Text for TTS (cleaned, ready to speak)
    display_text: str = ""  # Text for display (may have formatting)
    has_speech: bool = True  # Whether to speak this response
    is_system_command: bool = False  # Whether this is a system command (not spoken)
    system_action: str = ""  # System action to execute (e.g., "mode_switch")
    error: Optional[str] = None
    raw_llm_output: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "speech": self.speech_text,
            "display": self.display_text,
            "has_speech": self.has_speech,
            "is_system_command": self.is_system_command,
            "system_action": self.system_action,
        }


# ---------------------------------------------------------------------------
# Response Builder
# ---------------------------------------------------------------------------


class ResponseBuilder:
    """Build the final response from validated LLM output.

    Rules:
    - Clean text for TTS (remove markdown, URLs, code blocks)
    - Extract CHAT: content for speech
    - Track system commands separately
    - Handle errors gracefully
    """

    def __init__(self):
        pass

    def build(
        self,
        validation_result: ValidationResult,
        context: Optional[PipelineContext] = None,
    ) -> FinalResponse:
        """Build the final response.

        Args:
            validation_result: validated LLM output
            context: optional pipeline context

        Returns:
            FinalResponse ready for output
        """
        response = FinalResponse(raw_llm_output=validation_result.raw_output)

        if validation_result.errors and not validation_result.valid:
            return self._build_error_response(validation_result)

        # Extract text from validation result
        raw_text = validation_result.text or validation_result.raw_output

        if validation_result.response_type == "chat":
            return self._build_chat_response(raw_text, response)
        elif validation_result.response_type == "plan":
            return self._build_plan_response(validation_result, raw_text, response)
        else:
            return self._build_fallback_response(raw_text, response)

    def _build_chat_response(self, raw_text: str, response: FinalResponse) -> FinalResponse:
        """Build response for chat-type LLM output."""
        # Extract tag content if present
        cleaned = self._extract_tag_content(raw_text, "CHAT")
        if not cleaned:
            cleaned = raw_text

        # Clean for speech
        speech = self._clean_for_speech(cleaned)
        display = cleaned

        response.speech_text = speech
        response.display_text = display
        response.has_speech = bool(speech)
        return response

    def _build_plan_response(
        self,
        validation: ValidationResult,
        raw_text: str,
        response: FinalResponse,
    ) -> FinalResponse:
        """Build response for plan-type LLM output."""
        # Extract chat portion from raw text
        chat_text = self._extract_tag_content(raw_text, "CHAT")
        if not chat_text:
            chat_text = validation.text or "Processing your request Boss!"

        response.speech_text = self._clean_for_speech(chat_text)
        response.display_text = chat_text
        response.has_speech = bool(response.speech_text)

        # Check for system actions
        system_action = self._detect_system_action(raw_text, validation.valid_capabilities)
        if system_action:
            response.is_system_command = True
            response.system_action = system_action

        return response

    def _build_error_response(self, validation: ValidationResult) -> FinalResponse:
        """Build response for validation errors."""
        error_msg = validation.raw_output or ""

        # Try to extract usable text from error output
        chat_text = self._extract_tag_content(error_msg, "CHAT")
        if not chat_text:
            # Check if there's any text that looks like a response
            cleaned = self._clean_for_speech(error_msg)
            chat_text = cleaned if cleaned else "Sorry Boss, kuch error aa gaya."

        return FinalResponse(
            speech_text=chat_text,
            display_text=chat_text,
            has_speech=True,
            error="; ".join(validation.errors) if validation.errors else None,
            raw_llm_output=validation.raw_output,
        )

    def _build_fallback_response(self, raw_text: str, response: FinalResponse) -> FinalResponse:
        """Build fallback response when type is unknown."""
        cleaned = self._clean_for_speech(raw_text)
        chat_text = cleaned or "Haan Boss, ho jayega!"

        response.speech_text = chat_text
        response.display_text = raw_text
        response.has_speech = bool(chat_text)
        return response

    # ------------------------------------------------------------------
    # Text processing
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_tag_content(text: str, tag: str) -> str:
        """Extract content after a specific tag (e.g., 'CHAT:')."""
        pattern = rf"{tag}:\s*(.*?)(?:\s*(?:&&|$|SEARCH:|FILE_SEARCH:|OPEN_WEBSITE:|YOUTUBE:|WHATSAPP_MSG:|FILE_MOVE:|FILE_DELETE:|FILE_READ:|DUPLEX_MODE:|RESTART_SYSTEM:|SHUTDOWN_SYSTEM:|CLOSE_TAB|CLOSE_SPECIFIC_TABS:|STOP_BACKGROUND_BROWSER|BG_WHATSAPP_MSG:|BG_WHATSAPP_FILE:|ANALYZE_PROJECT|FIND_FUNCTION:|OPEN_APPLICATION:|BRAVE_WEBSITE:|BRAVE_YOUTUBE:|YOUTUBE_SEARCH:))"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""

    @staticmethod
    def _clean_for_speech(text: str) -> str:
        """Clean text for TTS output."""
        if not text:
            return ""

        # Remove code blocks
        text = re.sub(r"```.*?```", "I displayed the code on screen.", text, flags=re.DOTALL)
        # Remove URLs
        text = re.sub(r"https?://\S+", "link", text)
        # Remove markdown formatting
        text = text.replace("`", "").replace("*", "").replace("#", "").replace("_", " ")
        # Remove extra newlines
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Strip
        text = text.strip()

        return text

    @staticmethod
    def _detect_system_action(text: str, capabilities: list[str]) -> str:
        """Detect if the response contains a system action."""
        text_lower = text.lower()

        if "duplex" in text_lower:
            return "mode_switch:duplex"
        if "classic mode" in text_lower:
            return "mode_switch:classic"
        if "streaming" in text_lower:
            return "mode_switch:streaming"
        if "wake word" in text_lower:
            return "wake_word"
        if "shutdown" in text_lower:
            return "system:shutdown"
        if "restart" in text_lower:
            return "system:restart"
        if "background browser" in text_lower:
            return "background_browser"

        return ""

