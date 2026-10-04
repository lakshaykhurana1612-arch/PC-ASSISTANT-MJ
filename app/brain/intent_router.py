"""
Intent Router — Pre-LLM intent classification using regex + keywords.

This module NEVER calls an LLM. It uses pattern matching to identify
the user's intent before any LLM processing occurs.

Supported intents:
    CHAT, SYSTEM, SEARCH, FILE, WHATSAPP, BROWSER,
    DEVELOPER, VISION, AUTOMATION, FILE_READ, FILE_MOVE,
    FILE_DELETE, MODE_SWITCH, BACKGROUND_BROWSER

Usage:
    router = IntentRouter()
    result = router.classify("send resume to rahul on whatsapp")
    # result.intent = IntentType.WHATSAPP
    # result.confidence = 0.95
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Intent Types
# ---------------------------------------------------------------------------


class IntentType(Enum):
    """All supported intent types. NEVER call LLM to determine these."""

    CHAT = auto()              # Greetings, casual talk, opinions, jokes
    SYSTEM = auto()            # Change mode, wake word, exit
    SEARCH = auto()            # Web search / internet lookup
    FILE = auto()              # File search/locate/open
    FILE_READ = auto()         # Read/analyze/summarize file content
    FILE_MOVE = auto()         # Move file to folder
    FILE_DELETE = auto()       # Delete a file
    WHATSAPP = auto()          # WhatsApp message/file
    BROWSER = auto()           # Open websites, YouTube
    DEVELOPER = auto()         # Code analysis, fix, debug
    VISION = auto()            # Screen capture, OCR, UI detection
    AUTOMATION = auto()        # App launch, system control
    MODE_SWITCH = auto()       # Switch voice mode
    BACKGROUND_BROWSER = auto() # Background browser control
    AI_CHAT = auto()           # ChatGPT, Gemini, other AI chat platforms
    UNKNOWN = auto()           # Fallback to LLM


# ---------------------------------------------------------------------------
# Intent patterns (regex-based)
# ---------------------------------------------------------------------------

# Each intent has a list of (pattern, weight) tuples
# Higher weight = higher confidence when matched

_INTENT_PATTERNS: dict[IntentType, list[tuple[re.Pattern, float]]] = {}


def _compile(pairs: list[tuple[str, float]]) -> list[tuple[re.Pattern, float]]:
    """Compile string patterns to regex objects."""
    return [(re.compile(p, re.IGNORECASE), w) for p, w in pairs]


# ---- SYSTEM ----
_INTENT_PATTERNS[IntentType.SYSTEM] = _compile([
    (r"\b(exit|quit|shutdown|restart)\b", 1.0),
    (r"\b(go to sleep|sleep mode|stop listening)\b", 1.0),
    (r"\b(wake up|wake word)\b", 1.0),
    (r"\b(switch to|enable|disable|activate|deactivate)\s+(classic|streaming|duplex)\b", 1.0),
    (r"\b(toggle|turn on|turn off)\s+(duplex|wake|voice)\b", 0.9),
])

# ---- SEARCH ----
_INTENT_PATTERNS[IntentType.SEARCH] = _compile([
    (r"\b(search|google|look up|find online|internet)\s", 1.0),
    (r"\b(who|what|when|where|why|how)\s+(is|are|was|were|did|does|do|will|can)", 0.7),
    (r"\b(tell me about|what is|what's|who is|who's)\b", 0.6),
    (r"\b(news|weather|time|date|temperature|forecast)\b", 0.8),
    (r"\b(define|meaning of|definition of)\b", 0.8),
    (r"\b(score|result|match|game|fixture)\s", 0.7),
])

# ---- FILE ----
_INTENT_PATTERNS[IntentType.FILE] = _compile([
    (r"\b(find|locate|search for|look for)\s+(file|document|pdf|folder)\b", 1.0),
    (r"\bfile_search\b", 1.0),  # Direct tag
    (r"\bopen\s+(file|document|pdf|folder)\b", 0.9),
    (r"\b(find|locate|search|open)\s+[\w\s.]*\b", 0.5),  # Generic
    (r"\b(where is|show me|navigate to)\b", 0.7),
])

# ---- FILE READ ----
_INTENT_PATTERNS[IntentType.FILE_READ] = _compile([
    (r"\b(read|show|display|view)\s+(file|document|pdf)\b", 1.0),
    (r"\b(open and read|open file|read file)\b", 1.0),
    (r"\bFILE_READ\b", 1.0),  # Direct tag
    (r"\b(summarize|explain|analyze)\s+(this |the )?(file|document|pdf|code)\b", 0.9),
    (r"\b(what does|what is|tell me about)\s+(this |the )?(file|document)\b", 0.7),
])

# ---- FILE MOVE ----
_INTENT_PATTERNS[IntentType.FILE_MOVE] = _compile([
    (r"\b(move|copy|transfer)\s+(file|document|this)\s+(to|into)\b", 1.0),
    (r"\bFILE_MOVE\b", 1.0),
    (r"\b(move|put|place)\s+[\w\s.]+\s+(to|on|into)\s+(desktop|downloads|documents|folder)\b", 0.9),
])

# ---- FILE DELETE ----
_INTENT_PATTERNS[IntentType.FILE_DELETE] = _compile([
    (r"\b(delete|remove|trash|erase)\s+(file|document|this)\b", 1.0),
    (r"\bFILE_DELETE\b", 1.0),
    (r"\b(delete|remove|erase)\s+[\w\s.]+\b", 0.6),
])

# ---- WHATSAPP ----
_INTENT_PATTERNS[IntentType.WHATSAPP] = _compile([
    (r"\b(whatsapp|whats app|wa|wp)\b", 1.0),
    (r"\b(send|message|text)\s+\w+\s+(on|via|through|by)\s+(whatsapp|whats app)\b", 1.0),
    (r"\b(bg_whatsapp|whatsapp_message|whatsapp_file)\b", 1.0),
    (r"\b(send|message)\s+\w+\s+(resume|file|document|pdf)\s+(to|on)\b", 0.9),
    (r"\b(message|ping|text)\s+\w+\b", 0.5),  # Generic messaging
])

# ---- BROWSER ----
_INTENT_PATTERNS[IntentType.BROWSER] = _compile([
    (r"\b(open|go to|navigate to|launch)\s+(website|site|page|url|link)\b", 1.0),
    (r"\b(open|launch)\s+(brave|chrome|edge|browser)\b", 1.0),
    (r"\b(open_website|brave_website|youtube|youtube_search|brave_youtube)\b", 1.0),
    (r"\byoutube\b", 0.9),
    (r"\b(open|go to)\s+(https?://|www\.)\S+", 1.0),
    (r"\b(open|go to|launch)\s+[\w.]+\b", 0.5),
])

# ---- DEVELOPER ----
_INTENT_PATTERNS[IntentType.DEVELOPER] = _compile([
    (r"\b(analyze|scan|index)\s+(project|code|repository)\b", 1.0),
    (r"\bfind_function\b", 1.0),
    (r"\b(find|search)\s+(function|class|method)\b", 0.9),
    (r"\b(analyze_project|project analysis)\b", 1.0),
    (r"\b(fix|debug|repair|patch)\s+(this |the )?(bug|error|issue|code)\b", 0.9),
    (r"\b(show|list|get)\s+(functions|classes|imports)\b", 0.7),
])

# ---- VISION ----
_INTENT_PATTERNS[IntentType.VISION] = _compile([
    (r"\b(screenshot|screen capture|take a shot)\b", 1.0),
    (r"\b(ocr|read text from|extract text)\s+(screen|image|picture)\b", 1.0),
    (r"\b(what's on my|what do you see|describe screen)\b", 0.9),
    (r"\b(detect|find|locate)\s+(button|element|ui)\b", 0.8),
])

# ---- AUTOMATION ----
_INTENT_PATTERNS[IntentType.AUTOMATION] = _compile([
    (r"\b(open|launch|start)\s+(app|application|program|software)\b", 1.0),
    (r"\b(restart_system|shutdown_system|close_tab|close_specific)\b", 1.0),
    (r"\b(restart|shutdown)\s+(the )?(computer|pc|system|laptop)\b", 1.0),
    (r"\bclose\s+(browser|tab|window)\b", 0.8),
    (r"\bopen_application\b", 1.0),
])

# ---- MODE SWITCH ----
_INTENT_PATTERNS[IntentType.MODE_SWITCH] = _compile([
    (r"\b(duplex_mode|enter duplex|start duplex|stop duplex)\b", 1.0),
    (r"\b(switch to|enable|disable)\s+(classic|streaming|duplex)\s+(mode)?\b", 1.0),
    (r"\b(classic mode|streaming mode|duplex mode)\b", 1.0),
])

# ---- BACKGROUND BROWSER ----
_INTENT_PATTERNS[IntentType.BACKGROUND_BROWSER] = _compile([
    (r"\b(stop_background_browser|background browser)\b", 1.0),
    (r"\bstop\s+(the )?(background )?browser\b", 0.9),
])

# ---- AI CHAT (ChatGPT, Gemini) ----
_INTENT_PATTERNS[IntentType.AI_CHAT] = _compile([
    (r"\b(chatgpt|chat gpt|chai gpt|chagpt)\b", 1.0),
    (r"\b(gemini|google gemini)\b", 1.0),
    (r"\b(ask|use|search|query|prompt)\s+(on|in|using)\s+(chatgpt|gemini)\b", 1.0),
    (r"\b(open_chatgpt|open_gemini|open_chatai)\b", 1.0),
    (r"\b(make|create|generate)\s+(an?\s+)?(image|picture|photo|art)\s+(in|on|using)\s+(chatgpt|gemini)\b", 1.0),
    (r"\b(on|in)\s+(chatgpt|gemini)\b", 0.9),
])

# ---- CHAT (catch-all) ----
# Patterns that STRONGLY indicate chat (not routed to other intents)
_INTENT_PATTERNS[IntentType.CHAT] = _compile([
    (r"\b(hello|hi|hey|namaste|good morning|good evening|good night)\b", 0.5),
    (r"\b(how are you|kaise ho|kya haal|what's up|sup)\b", 1.0),
    (r"\b(thanks|thank you|dhanyavaad|shukriya)\b", 0.8),
    (r"\b(who are you|what can you do|apna parichay|intro)\b", 1.0),
    (r"\b(tell me a joke|joke|funny|mazaak)\b", 1.0),
    (r"\b(what do you think|your opinion|tum kya sochte)\b", 0.9),
    (r"\b(i'm (feeling|bored|happy|sad))\b", 0.8),
])


# ---------------------------------------------------------------------------
# Intent Router
# ---------------------------------------------------------------------------


@dataclass
class IntentResult:
    """Result of intent classification."""

    intent: IntentType = IntentType.UNKNOWN
    confidence: float = 0.0
    matched_patterns: list[str] = field(default_factory=list)
    normalized_text: str = ""
    raw_text: str = ""
    is_system_command: bool = False


class IntentRouter:
    """Classify user input intent using regex + keyword patterns.

    Usage:
        router = IntentRouter()
        result = router.classify("open chrome and search for python")
        # result.intent = IntentType.BROWSER  (multiple intents supported)
        # result.confidence = 0.95
    """

    def __init__(self):
        self._patterns = _INTENT_PATTERNS

    def classify(self, text: str) -> IntentResult:
        """Classify the intent of the given text.

        Args:
            text: normalized user input (lowercase, trimmed)

        Returns:
            IntentResult with the highest-confidence intent
        """
        if not text or not text.strip():
            return IntentResult(
                intent=IntentType.UNKNOWN,
                raw_text=text,
                normalized_text=text,
            )

        normalized = text.strip().lower()
        # Remove punctuation for matching
        clean = re.sub(r"[^\w\s]", " ", normalized)
        clean = re.sub(r"\s+", " ", clean).strip()

        scores: dict[IntentType, float] = {}
        matched_patterns: list[str] = []

        for intent, patterns in self._patterns.items():
            total_score = 0.0
            for pattern, weight in patterns:
                match = pattern.search(clean)
                if match:
                    total_score += weight
                    matched_patterns.append(f"{intent.name}:{match.group(0)}")
            if total_score > 0:
                scores[intent] = total_score

        if not scores:
            return IntentResult(
                intent=IntentType.UNKNOWN,
                confidence=0.0,
                normalized_text=normalized,
                raw_text=text,
            )

        # Get the highest scoring intent
        best_intent = max(scores, key=scores.get)
        best_score = scores[best_intent]

        # Calculate confidence (normalize: cap at 1.0)
        confidence = min(best_score, 2.0) / 2.0

        # Check if it's a system command
        is_system = best_intent in (
            IntentType.SYSTEM,
            IntentType.MODE_SWITCH,
            IntentType.BACKGROUND_BROWSER,
        )

        return IntentResult(
            intent=best_intent,
            confidence=confidence,
            matched_patterns=matched_patterns,
            normalized_text=normalized,
            raw_text=text,
            is_system_command=is_system,
        )

    def classify_all(self, text: str) -> list[tuple[IntentType, float]]:
        """Get all intents with their scores, sorted by confidence.

        Useful for multi-intent detection (e.g., "file search + whatsapp")
        """
        if not text:
            return []

        clean = re.sub(r"[^\w\s]", " ", text.lower().strip())
        clean = re.sub(r"\s+", " ", clean).strip()

        scores: list[tuple[IntentType, float]] = []

        for intent, patterns in self._patterns.items():
            total_score = 0.0
            for pattern, weight in patterns:
                if pattern.search(clean):
                    total_score += weight
            if total_score > 0:
                confidence = min(total_score, 2.0) / 2.0
                scores.append((intent, confidence))

        return sorted(scores, key=lambda x: x[1], reverse=True)

    def has_intent(self, text: str, intent: IntentType) -> bool:
        """Check if text has a specific intent."""
        result = self.classify(text)
        return result.intent == intent

