"""
Input Normalizer — Prepares raw user input for intent routing.

Handles:
- Trimming whitespace
- Lowercasing
- Removing filler words (optional)
- Normalizing Hinglish spellings
- Extracting clean text for intent classification

This is the FIRST stage of the pipeline. Always runs before IntentRouter.
"""

from __future__ import annotations

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input Normalizer
# ---------------------------------------------------------------------------


class InputNormalizer:
    """Normalize raw user input for intent routing and LLM processing.

    Usage:
        normalizer = InputNormalizer()
        result = normalizer.normalize("  Hey MJ,  open  chrome  ")
        # result.text = "hey mj open chrome"
        # result.is_empty = False
    """

    def __init__(self):
        # Filler words to remove (optional, configurable)
        self._filler_words: set[str] = {
            "um", "uh", "hmm", "ah", "oh", "like", "actually",
            "basically", "literally", "honestly", "i mean",
        }
        # Wake word variants
        self._wake_words: set[str] = {"mj", "m j", "hey mj", "ok mj", "hello mj"}

    def normalize(self, raw_text: str) -> "NormalizedInput":
        """Normalize the raw input text.

        Args:
            raw_text: raw string from speech or text input

        Returns:
            NormalizedInput with cleaned text and metadata
        """
        if not raw_text or not raw_text.strip():
            return NormalizedInput(
                original="",
                text="",
                is_empty=True,
                clean_text="",
            )

        original = raw_text.strip()
        text = original.lower()

        # Remove excessive whitespace
        text = re.sub(r"\s+", " ", text)

        # Store pre-wake-word-removal text for wake detection
        had_wake_word, text_without_wake = self._strip_wake_word(text)

        # Clean text (remove filler words)
        clean = self._remove_fillers(text_without_wake)
        clean = clean.strip()

        return NormalizedInput(
            original=original,
            text=text,
            clean_text=clean,
            is_empty=not bool(clean),
            had_wake_word=had_wake_word,
            text_without_wake=text_without_wake,
        )

    def _strip_wake_word(self, text: str) -> tuple[bool, str]:
        """Remove wake word from the beginning of text if present.

        Returns:
            (had_wake_word, text_without_wake)
        """
        lowered = text.lower().strip()

        for ww in sorted(self._wake_words, key=len, reverse=True):
            if lowered.startswith(ww):
                remainder = lowered[len(ww):].strip()
                # Remove common separators
                for sep in [",", ".", "!", ":", " "]:
                    if remainder.startswith(sep):
                        remainder = remainder[len(sep):].strip()
                return True, remainder

        return False, text

    def _remove_fillers(self, text: str) -> str:
        """Remove common filler words."""
        words = text.split()
        clean = [w for w in words if w not in self._filler_words]
        return " ".join(clean)

    def is_wake_word_only(self, text: str) -> bool:
        """Check if the input is just a wake word."""
        lowered = text.lower().strip()
        for ww in self._wake_words:
            if lowered == ww:
                return True
        return False

    def extract_keywords(self, text: str, max_keywords: int = 5) -> list[str]:
        """Extract meaningful keywords from text (removes stop words)."""
        stop_words = {
            "a", "an", "the", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "shall", "can",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "as", "into", "through", "during", "before", "after", "above",
            "below", "between", "out", "off", "over", "under", "again",
            "further", "then", "once", "here", "there", "when", "where",
            "why", "how", "all", "each", "every", "both", "few", "more",
            "most", "other", "some", "such", "no", "nor", "not", "only",
            "own", "same", "so", "than", "too", "very", "just", "because",
            "and", "but", "or", "if", "while", "although", "since",
            "about", "up", "down",
        }
        words = text.lower().split()
        keywords = [w for w in words if w not in stop_words and len(w) > 1]
        return keywords[:max_keywords]


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


from dataclasses import dataclass, field


@dataclass
class NormalizedInput:
    """Result of input normalization."""

    original: str = ""
    text: str = ""  # Lowercased, trimmed
    clean_text: str = ""  # Without fillers
    is_empty: bool = True
    had_wake_word: bool = False
    text_without_wake: str = ""
    keywords: list[str] = field(default_factory=list)
    confidence: float = 1.0

