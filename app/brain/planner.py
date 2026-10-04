"""
Planner — Task planner that breaks down user requests into capability-based plans.

The Planner works with ABSTRACT CAPABILITIES (not concrete tool tags).
It sits BEFORE the LLM call and structures the user's request into
a plan that the LLM can fill in.

Rules:
1. Planner NEVER references concrete tags (FILE_SEARCH, OPEN_WEBSITE, etc.)
2. Planner only references Capability enum values
3. The LLM receives capability-based context and produces capability-based plans
4. The Executor maps capabilities back to concrete tags

Usage:
    planner = Planner()
    plan = planner.create_plan(
        normalized_input="send resume to rahul on whatsapp",
        intent=IntentType.WHATSAPP,
    )
    # plan.tasks = [
    #   Task(description="Find resume file", capability=Capability.FILE_SEARCH, ...),
    #   Task(description="Send file via WhatsApp", capability=Capability.WHATSAPP_FILE, ...),
    # ]
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from typing import Any, Optional

from app.brain.intent_router import IntentType
from app.brain.tool_registry import Capability

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plan dataclasses
# ---------------------------------------------------------------------------


class PlanStatus(Enum):
    DRAFT = auto()
    SUBMITTED = auto()
    VALIDATED = auto()
    EXECUTING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


@dataclass
class Step:
    """A single step in a task — maps to a capability."""

    id: str = ""
    capability: str = ""  # Capability enum name (e.g., "FILE_SEARCH")
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)  # Step IDs this depends on
    status: str = "pending"  # pending, running, completed, failed, skipped
    result: Any = None
    error: Optional[str] = None


@dataclass
class Task:
    """A task consisting of one or more steps."""

    id: str = ""
    description: str = ""
    intent: str = ""
    steps: list[Step] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    priority: int = 5  # 1 (highest) to 10 (lowest)


@dataclass
class Plan:
    """Complete plan consisting of one or more tasks."""

    id: str = ""
    user_input: str = ""
    intent: str = ""
    tasks: list[Task] = field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    context: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_json(self) -> str:
        """Serialize plan to JSON (for LLM consumption)."""
        return json.dumps(asdict(self), indent=2, default=str)

    @property
    def total_steps(self) -> int:
        return sum(len(t.steps) for t in self.tasks)

    @property
    def all_step_ids(self) -> list[str]:
        return [s.id for t in self.tasks for s in t.steps]


# ---------------------------------------------------------------------------
# Simple intent-to-plan mappers (pre-LLM structural planning)
# ---------------------------------------------------------------------------


class Planner:
    """Creates structured plans from user input + intent.

    The Planner breaks down complex requests into capability-based tasks
    BEFORE any LLM call. This ensures the LLM receives a structured plan
    rather than raw user text.

    Usage:
        planner = Planner()
        plan = planner.create_plan("send resume to rahul", IntentType.WHATSAPP)
        # plan has Task[find_file] and Task[send_whatsapp]
    """

    def __init__(self):
        self._intent_mappers: dict[IntentType, callable] = {
            IntentType.CHAT: self._plan_chat,
            IntentType.SEARCH: self._plan_search,
            IntentType.FILE: self._plan_file_search,
            IntentType.FILE_READ: self._plan_file_read,
            IntentType.FILE_MOVE: self._plan_file_move,
            IntentType.FILE_DELETE: self._plan_file_delete,
            IntentType.WHATSAPP: self._plan_whatsapp,
            IntentType.BROWSER: self._plan_browser,
            IntentType.DEVELOPER: self._plan_developer,
            IntentType.VISION: self._plan_vision,
            IntentType.AUTOMATION: self._plan_automation,
            IntentType.SYSTEM: self._plan_system,
            IntentType.MODE_SWITCH: self._plan_mode_switch,
            IntentType.BACKGROUND_BROWSER: self._plan_background_browser,
            IntentType.AI_CHAT: self._plan_ai_chat,
            IntentType.UNKNOWN: self._plan_unknown,
        }

    def create_plan(
        self,
        normalized_input: str,
        intent: IntentType,
        additional_context: Optional[dict[str, Any]] = None,
    ) -> Plan:
        """Create a structured plan from user input and intent.

        Args:
            normalized_input: normalized user input
            intent: classified intent
            additional_context: optional extra context

        Returns:
            Plan with structured tasks and steps
        """
        mapper = self._intent_mappers.get(intent, self._plan_unknown)
        plan = Plan(
            id=self._generate_id(),
            user_input=normalized_input,
            intent=intent.name.lower(),
            status=PlanStatus.DRAFT,
        )

        try:
            plan.tasks = mapper(normalized_input, additional_context or {})
        except Exception as e:
            logger.error(f"Planner error for intent {intent}: {e}")
            plan.tasks = self._fallback_plan(normalized_input)
            plan.error = str(e)

        return plan

    # ------------------------------------------------------------------
    # Intent-specific mappers
    # ------------------------------------------------------------------

    def _plan_chat(self, text: str, ctx: dict) -> list[Task]:
        """Chat intent — no automation steps, just conversation."""
        return [
            Task(
                id=self._generate_id(),
                description=f"Respond to: {text}",
                intent="chat",
                steps=[
                    Step(
                        id=self._generate_id(),
                        capability=Capability.CHAT.name,
                        description="Generate natural chat response",
                        parameters={"text": text, "style": "hinglish"},
                    )
                ],
            )
        ]

    def _plan_search(self, text: str, ctx: dict) -> list[Task]:
        """Web search intent — search the internet."""
        # Extract search query (remove "search" prefix)
        query = text.lower()
        for prefix in ["search for", "search", "google", "look up", "find online"]:
            if query.startswith(prefix):
                query = query[len(prefix):].strip()
                break

        return [
            Task(
                id=self._generate_id(),
                description=f"Search the web for: {query or text}",
                intent="search",
                steps=[
                    Step(
                        id=self._generate_id(),
                        capability=Capability.WEB_SEARCH.name,
                        description="Perform web search",
                        parameters={"query": query or text},
                    )
                ],
            )
        ]

    def _plan_file_search(self, text: str, ctx: dict) -> list[Task]:
        """File search intent — find a file."""
        # Extract filename/keywords
        query = text.lower()
        for prefix in ["find file", "locate file", "search file", "open file", "find", "locate", "search for", "open"]:
            if query.startswith(prefix):
                query = query[len(prefix):].strip()
                break
        # Remove leading "the" "a" "an"
        for prefix in ["the ", "a ", "an "]:
            if query.startswith(prefix):
                query = query[len(prefix):].strip()
                break

        return [
            Task(
                id=self._generate_id(),
                description=f"Find file: {query or text}",
                intent="file_search",
                steps=[
                    Step(
                        id=self._generate_id(),
                        capability=Capability.FILE_SEARCH.name,
                        description="Search for file on computer",
                        parameters={"query": query or text},
                    )
                ],
            )
        ]

    def _plan_file_read(self, text: str, ctx: dict) -> list[Task]:
        """File read intent — read and analyze a file."""
        # Extract filename and optional question
        file_parts = text.split("|")
        filename = file_parts[0].strip() if file_parts else text
        question = file_parts[1].strip() if len(file_parts) > 1 else ""

        # Clean filename prefix
        for prefix in ["read file", "read", "open and read", "show file"]:
            if filename.lower().startswith(prefix):
                filename = filename[len(prefix):].strip()
                break

        return [
            Task(
                id=self._generate_id(),
                description=f"Read and analyze file: {filename}",
                intent="file_read",
                steps=[
                    Step(
                        id=self._generate_id(),
                        capability=Capability.FILE_SEARCH.name,
                        description="Find the file on computer",
                        parameters={"query": filename},
                    ),
                    Step(
                        id=self._generate_id(),
                        capability=Capability.FILE_READ.name,
                        description="Read file content and answer",
                        parameters={
                            "filename": filename,
                            "question": question or "Summarize this file.",
                        },
                        depends_on=[],
                    ),
                ],
            )
        ]

    def _plan_file_move(self, text: str, ctx: dict) -> list[Task]:
        """File move intent."""
        return [
            Task(
                id=self._generate_id(),
                description=f"Move file: {text}",
                intent="file_move",
                steps=[
                    Step(
                        id=self._generate_id(),
                        capability=Capability.FILE_MOVE.name,
                        description="Move file to destination",
                        parameters={"request": text},
                    )
                ],
            )
        ]

    def _plan_file_delete(self, text: str, ctx: dict) -> list[Task]:
        """File delete intent."""
        return [
            Task(
                id=self._generate_id(),
                description=f"Delete file: {text}",
                intent="file_delete",
                steps=[
                    Step(
                        id=self._generate_id(),
                        capability=Capability.FILE_DELETE.name,
                        description="Permanently delete file",
                        parameters={"request": text},
                    )
                ],
            )
        ]

    def _plan_whatsapp(self, text: str, ctx: dict) -> list[Task]:
        """WhatsApp intent — detect send/file operations."""
        has_file_keywords = any(w in text.lower() for w in ["resume", "file", "document", "pdf"])
        has_send_keyword = any(w in text.lower() for w in ["send", "message", "text"])

        tasks = []

        # If there's a file involved, add file search step
        if has_file_keywords:
            tasks.append(
                Task(
                    id=self._generate_id(),
                    description="Find the file to send",
                    intent="file_search",
                    steps=[
                        Step(
                            id=self._generate_id(),
                            capability=Capability.FILE_SEARCH.name,
                            description="Find the file for WhatsApp",
                            parameters={"query": text},
                        )
                    ],
                )
            )

        # Add WhatsApp send step
        if has_send_keyword:
            cap = Capability.WHATSAPP_FILE if has_file_keywords else Capability.WHATSAPP_MESSAGE
            tasks.append(
                Task(
                    id=self._generate_id(),
                    description="Send via WhatsApp",
                    intent="whatsapp",
                    steps=[
                        Step(
                            id=self._generate_id(),
                            capability=cap.name,
                            description="Send message/file on WhatsApp",
                            parameters={"request": text},
                        )
                    ],
                )
            )

        return tasks if tasks else self._fallback_plan(text)

    def _plan_browser(self, text: str, ctx: dict) -> list[Task]:
        """Browser intent — open website or YouTube."""
        is_youtube = any(w in text.lower() for w in ["youtube", "yt"])
        is_brave = any(w in text.lower() for w in ["brave"])

        cap = Capability.WEB_BROWSER
        tags = []
        if is_youtube and is_brave:
            tags = ["BRAVE_YOUTUBE"]
        elif is_youtube:
            tags = ["YOUTUBE"]
        elif is_brave:
            tags = ["BRAVE_WEBSITE"]
        else:
            tags = ["OPEN_WEBSITE"]

        return [
            Task(
                id=self._generate_id(),
                description=f"Open browser: {text}",
                intent="browser",
                steps=[
                    Step(
                        id=self._generate_id(),
                        capability=cap.name,
                        description="Open website in browser",
                        parameters={"request": text, "suggested_tags": tags},
                    )
                ],
            )
        ]

    def _plan_developer(self, text: str, ctx: dict) -> list[Task]:
        """Developer intent — code analysis."""
        is_analyze = any(w in text.lower() for w in ["analyze", "scan", "index"])
        is_find = any(w in text.lower() for w in ["find function", "find class", "search function"])

        tasks = []
        if is_analyze:
            tasks.append(
                Task(
                    id=self._generate_id(),
                    description="Analyze project structure",
                    intent="developer",
                    steps=[
                        Step(
                            id=self._generate_id(),
                            capability=Capability.PROJECT_ANALYZE.name,
                            description="Scan and analyze project",
                            parameters={"request": text},
                        )
                    ],
                )
            )
        if is_find:
            tasks.append(
                Task(
                    id=self._generate_id(),
                    description="Find function in project",
                    intent="developer",
                    steps=[
                        Step(
                            id=self._generate_id(),
                            capability=Capability.FUNCTION_FIND.name,
                            description="Search for function definition",
                            parameters={"request": text},
                        )
                    ],
                )
            )

        return tasks if tasks else self._fallback_plan(text)

    def _plan_vision(self, text: str, ctx: dict) -> list[Task]:
        """Vision intent — screen/OCR operations."""
        return [
            Task(
                id=self._generate_id(),
                description=f"Vision operation: {text}",
                intent="vision",
                steps=[
                    Step(
                        id=self._generate_id(),
                        capability=Capability.SCREEN_CAPTURE.name,
                        description="Capture screen or process image",
                        parameters={"request": text},
                    )
                ],
            )
        ]

    def _plan_automation(self, text: str, ctx: dict) -> list[Task]:
        """Automation intent — app launch / system control."""
        is_system = any(w in text.lower() for w in ["restart", "shutdown"])
        cap = Capability.SYSTEM_CONTROL if is_system else Capability.APP_LAUNCH

        return [
            Task(
                id=self._generate_id(),
                description=f"Automation: {text}",
                intent="automation",
                steps=[
                    Step(
                        id=self._generate_id(),
                        capability=cap.name,
                        description="Execute system or app action",
                        parameters={"request": text},
                    )
                ],
            )
        ]

    def _plan_system(self, text: str, ctx: dict) -> list[Task]:
        """System intent — mode/configuration changes."""
        return [
            Task(
                id=self._generate_id(),
                description=f"System command: {text}",
                intent="system",
                steps=[
                    Step(
                        id=self._generate_id(),
                        capability=Capability.SYSTEM_CONTROL.name,
                        description="Execute system command",
                        parameters={"request": text},
                    )
                ],
            )
        ]

    def _plan_mode_switch(self, text: str, ctx: dict) -> list[Task]:
        """Mode switch intent."""
        return [
            Task(
                id=self._generate_id(),
                description=f"Switch mode: {text}",
                intent="mode_switch",
                steps=[
                    Step(
                        id=self._generate_id(),
                        capability=Capability.MODE_SWITCH.name,
                        description="Change MJ's voice mode",
                        parameters={"request": text},
                    )
                ],
            )
        ]

    def _plan_background_browser(self, text: str, ctx: dict) -> list[Task]:
        """Background browser control intent."""
        return [
            Task(
                id=self._generate_id(),
                description="Stop background browser",
                intent="background_browser",
                steps=[
                    Step(
                        id=self._generate_id(),
                        capability=Capability.BACKGROUND_BROWSER.name,
                        description="Stop Playwright browser",
                        parameters={},
                    )
                ],
            )
        ]

    def _plan_ai_chat(self, text: str, ctx: dict) -> list[Task]:
        """AI Chat intent — open ChatGPT or Gemini with a query."""
        # Determine which platform
        is_gemini = any(w in text.lower() for w in ["gemini", "google gemini"])
        is_chatgpt = any(w in text.lower() for w in ["chatgpt", "chat gpt", "chai gpt", "chagpt", "chat ai", "chatai"])
        
        # Determine suggested tag
        if is_gemini:
            suggested_tag = "OPEN_GEMINI"
        else:
            suggested_tag = "OPEN_CHATGPT"

        # Extract query (remove platform mentions)
        query = text.lower()
        for phrase in ["search on", "search in", "ask on", "ask in", "use on", "use in", 
                        "on chatgpt", "on gemini", "in chatgpt", "in gemini",
                        "using chatgpt", "using gemini", "make a image of", "make an image of",
                        "create an image of", "create a image of", "generate an image of",
                        "generate a image of", "make image of", "create image of"]:
            query = query.replace(phrase, "").strip()
        for w in ["chatgpt", "chat gpt", "gemini", "google gemini", "chai gpt", "chagpt", "chatai"]:
            query = query.replace(w, "").strip()
            
        query = query.strip().strip('"').strip("'").strip()
        if not query:
            query = text

        return [
            Task(
                id=self._generate_id(),
                description=f"Open AI chat: {query}",
                intent="ai_chat",
                steps=[
                    Step(
                        id=self._generate_id(),
                        capability=Capability.AI_CHAT.name,
                        description=f"Open {suggested_tag.replace('OPEN_', '').title()} with query",
                        parameters={"query": query, "suggested_tag": suggested_tag},
                    )
                ],
            )
        ]

    def _plan_unknown(self, text: str, ctx: dict) -> list[Task]:
        """Unknown intent — let LLM handle it."""
        return self._fallback_plan(text)

    def _fallback_plan(self, text: str) -> list[Task]:
        """Fallback plan when no specific mapper matches."""
        return [
            Task(
                id=self._generate_id(),
                description=f"Process user request: {text[:100]}",
                intent="unknown",
                steps=[
                    Step(
                        id=self._generate_id(),
                        capability=Capability.CHAT.name,
                        description="Analyze and respond to user request",
                        parameters={"text": text},
                    )
                ],
            )
        ]

    @staticmethod
    def _generate_id() -> str:
        """Generate a unique ID for plans/tasks/steps."""
        return uuid.uuid4().hex[:12]

