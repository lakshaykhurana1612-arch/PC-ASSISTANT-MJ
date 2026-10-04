"""
Tool Registry — Single source of truth for all MJ tools/capabilities.

All tools must be registered here. The Planner uses abstract capability names,
and the Validator checks LLM output against this registry to reject hallucinations.

Usage:
    registry = ToolRegistry.get_instance()
    tool = registry.get("FILE_SEARCH")
    all_tools = registry.list_tools()
    registry.validate_tool("FAKE_TOOL")  # Returns False

To add a new tool in the future:
    1. Define a ToolDefinition here
    2. Add the handler in execute_smart_action() or executor.py
    3. Done — no other file needs changing
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Capability categories (abstract — used by Planner, NOT tags)
# ---------------------------------------------------------------------------


class Capability(Enum):
    """Abstract capability categories.

    The Planner works with these. The Executor maps these to concrete tool tags.
    """

    # Chat / Conversation
    CHAT = auto()

    # Web operations
    WEB_SEARCH = auto()
    WEB_BROWSER = auto()

    # File operations
    FILE_SEARCH = auto()
    FILE_READ = auto()
    FILE_MOVE = auto()
    FILE_DELETE = auto()
    FILE_ORGANIZE = auto()

    # Communication
    WHATSAPP_MESSAGE = auto()
    WHATSAPP_FILE = auto()
    WHATSAPP_BACKGROUND = auto()

    # System operations
    SYSTEM_CONTROL = auto()  # restart, shutdown
    APP_LAUNCH = auto()
    TAB_MANAGE = auto()

    # Developer operations
    PROJECT_ANALYZE = auto()
    FUNCTION_FIND = auto()
    CODE_EDIT = auto()
    CODE_PATCH = auto()

    # Vision operations
    SCREEN_CAPTURE = auto()
    OCR = auto()
    UI_DETECT = auto()

    # AI Chat platforms (ChatGPT, Gemini, etc.)
    AI_CHAT = auto()

    # MJ System
    MODE_SWITCH = auto()  # duplex, streaming, classic
    WAKE_WORD = auto()
    BACKGROUND_BROWSER = auto()


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


@dataclass
class ToolDefinition:
    """Defines a registered tool/capability.

    The LLM is told about capabilities, not raw tags.
    The executor maps capabilities to concrete tags.
    """

    # Unique tool name (used internally)
    name: str

    # Abstract capability this tool belongs to
    capability: Capability

    # Human-readable description (for LLM prompt)
    description: str

    # Parameter schema (JSON-like)
    parameters: dict[str, Any] = field(default_factory=dict)

    # Concrete tags that trigger this tool (backward compatibility)
    tags: list[str] = field(default_factory=list)

    # Whether this tool requires internet
    requires_internet: bool = False

    # Whether this tool requires user approval
    requires_approval: bool = False

    # Handler module path (for future dynamic loading)
    handler: str = ""

    # Example usages for LLM
    examples: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tool Registry (Singleton)
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Central registry of all available tools.

    Singleton pattern — one registry for the entire application.
    """

    _instance: Optional["ToolRegistry"] = None

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._capability_map: dict[Capability, list[ToolDefinition]] = {}
        self._tag_map: dict[str, ToolDefinition] = {}
        self._register_all()

    @classmethod
    def get_instance(cls) -> "ToolRegistry":
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def _register(self, tool: ToolDefinition) -> None:
        """Register a single tool."""
        self._tools[tool.name] = tool

        # Capability map
        if tool.capability not in self._capability_map:
            self._capability_map[tool.capability] = []
        self._capability_map[tool.capability].append(tool)

        # Tag map (for backward compat)
        for tag in tool.tags:
            self._tag_map[tag.upper()] = tool

    def _register_all(self) -> None:
        """Register all built-in tools."""
        tools = self._builtin_tools()
        for t in tools:
            self._register(t)
        logger.info(f"Registered {len(tools)} tools across {len(self._capability_map)} capabilities.")

    # ------------------------------------------------------------------
    # Built-in tool definitions
    # ------------------------------------------------------------------

    @staticmethod
    def _builtin_tools() -> list[ToolDefinition]:
        """Define all built-in tools."""
        return [
            # ---- CHAT ----
            ToolDefinition(
                name="chat",
                capability=Capability.CHAT,
                description="Natural conversation with the user. Respond in Hinglish with MJ's personality.",
                tags=["CHAT"],
                examples=[
                    "CHAT: Haan Boss, ho jayega!",
                    "CHAT: Arre yaar, ye toh easy hai.",
                ],
            ),

            # ---- WEB SEARCH ----
            ToolDefinition(
                name="web_search",
                capability=Capability.WEB_SEARCH,
                description="Search the internet for current information, news, or facts.",
                parameters={"query": "string (the search query)"},
                tags=["SEARCH"],
                requires_internet=True,
                examples=[
                    "SEARCH: today's news headlines",
                    "SEARCH: temperature in Delhi today",
                ],
            ),

            # ---- WEB BROWSER ----
            ToolDefinition(
                name="open_website",
                capability=Capability.WEB_BROWSER,
                description="Open a website in the default or Brave browser.",
                parameters={"url": "string (full URL or search term)", "browser": "string (optional: brave, chrome, default)"},
                tags=["OPEN_WEBSITE", "BRAVE_WEBSITE"],
                requires_internet=True,
                examples=[
                    "OPEN_WEBSITE: https://youtube.com",
                    "BRAVE_WEBSITE: github.com",
                ],
            ),
            ToolDefinition(
                name="youtube_search",
                capability=Capability.WEB_BROWSER,
                description="Search and play videos on YouTube.",
                parameters={"query": "string (video search term)"},
                tags=["YOUTUBE", "YOUTUBE_SEARCH", "BRAVE_YOUTUBE"],
                requires_internet=True,
                examples=[
                    "YOUTUBE: funny cat videos",
                    "BRAVE_YOUTUBE: python tutorial",
                ],
            ),

            # ---- FILE SEARCH ----
            ToolDefinition(
                name="file_search",
                capability=Capability.FILE_SEARCH,
                description="Search for a file on the computer by name and optionally open it.",
                parameters={"query": "string (filename or keywords)"},
                tags=["FILE_SEARCH"],
                examples=[
                    "FILE_SEARCH: resume.pdf",
                    "FILE_SEARCH: project report",
                ],
            ),

            # ---- FILE READ ----
            ToolDefinition(
                name="file_read",
                capability=Capability.FILE_READ,
                description="Read a file's content and answer questions about it.",
                parameters={"filename": "string", "question": "string (optional, what to ask about the file)"},
                tags=["FILE_READ"],
                examples=[
                    "FILE_READ: notes.pdf | Summarize this document.",
                    "FILE_READ: main.py | What does this function do?",
                ],
            ),

            # ---- FILE MOVE ----
            ToolDefinition(
                name="file_move",
                capability=Capability.FILE_MOVE,
                description="Move a file to another folder (desktop, documents, downloads, etc.).",
                parameters={"filename": "string", "destination": "string (folder name or path)"},
                tags=["FILE_MOVE"],
                examples=[
                    "FILE_MOVE: photo.jpg | desktop",
                    "FILE_MOVE: report.pdf | documents",
                ],
            ),

            # ---- FILE DELETE ----
            ToolDefinition(
                name="file_delete",
                capability=Capability.FILE_DELETE,
                description="Permanently delete a file.",
                parameters={"filename": "string"},
                tags=["FILE_DELETE"],
                requires_approval=True,
                examples=[
                    "FILE_DELETE: temp.txt",
                ],
            ),

            # ---- WHATSAPP MESSAGE ----
            ToolDefinition(
                name="whatsapp_message",
                capability=Capability.WHATSAPP_MESSAGE,
                description="Send a WhatsApp message to a contact using WhatsApp Web UI.",
                parameters={"contact": "string (name or phone number)", "message": "string"},
                tags=["WHATSAPP_MSG"],
                requires_internet=True,
                examples=[
                    "WHATSAPP_MSG: Rohan | Hey, I'll send the file now.",
                ],
            ),

            # ---- WHATSAPP FILE ----
            ToolDefinition(
                name="whatsapp_file",
                capability=Capability.WHATSAPP_FILE,
                description="Send a file via WhatsApp to a contact.",
                parameters={"contact": "string (name)", "filename": "string"},
                tags=["WHATSAPP_FILE"],
                requires_internet=True,
                examples=[
                    "WHATSAPP_FILE: Rohan | resume.pdf",
                ],
            ),

            # ---- WHATSAPP BACKGROUND ----
            ToolDefinition(
                name="whatsapp_background_message",
                capability=Capability.WHATSAPP_BACKGROUND,
                description="Send WhatsApp message in background without opening the UI.",
                parameters={"contact": "string (phone number or name)", "message": "string"},
                tags=["BG_WHATSAPP_MSG", "BG_WHATSAPP_FILE"],
                requires_internet=True,
                examples=[
                    "BG_WHATSAPP_MSG: +911234567890 | Hey, this is MJ!",
                ],
            ),

            # ---- SYSTEM CONTROL ----
            ToolDefinition(
                name="system_restart",
                capability=Capability.SYSTEM_CONTROL,
                description="Restart the computer (requires password).",
                tags=["RESTART_SYSTEM"],
                requires_approval=True,
            ),
            ToolDefinition(
                name="system_shutdown",
                capability=Capability.SYSTEM_CONTROL,
                description="Shut down the computer (requires password).",
                tags=["SHUTDOWN_SYSTEM"],
                requires_approval=True,
            ),

            # ---- APP LAUNCH ----
            ToolDefinition(
                name="app_launch",
                capability=Capability.APP_LAUNCH,
                description="Launch an application on the computer.",
                parameters={"app_name": "string (name of the app)"},
                tags=["OPEN_APPLICATION"],
                examples=[
                    "OPEN_APPLICATION: notepad",
                    "OPEN_APPLICATION: chrome",
                ],
            ),

            # ---- TAB MANAGE ----
            ToolDefinition(
                name="close_tab",
                capability=Capability.TAB_MANAGE,
                description="Close the current browser tab or close specific browser(s).",
                parameters={"target": "string (optional: browser name like chrome, brave, edge)"},
                tags=["CLOSE_TAB", "CLOSE_SPECIFIC_TABS"],
            ),

            # ---- PROJECT ANALYZE ----
            ToolDefinition(
                name="project_analyze",
                capability=Capability.PROJECT_ANALYZE,
                description="Analyze a project directory: count files, functions, classes, imports.",
                parameters={"project_path": "string (optional, defaults to D:/MJ)"},
                tags=["ANALYZE_PROJECT"],
            ),

            # ---- FUNCTION FIND ----
            ToolDefinition(
                name="function_find",
                capability=Capability.FUNCTION_FIND,
                description="Find a function definition across the project.",
                parameters={"function_name": "string"},
                tags=["FIND_FUNCTION"],
            ),

            # ---- MODE SWITCH ----
            ToolDefinition(
                name="mode_switch",
                capability=Capability.MODE_SWITCH,
                description="Switch MJ's voice mode: classic, streaming, or duplex.",
                parameters={"mode": "string (classic, streaming, duplex)"},
                tags=[],
            ),

            # ---- DUPLEX MODE ----
            ToolDefinition(
                name="duplex_mode",
                capability=Capability.MODE_SWITCH,
                description="Enter or exit duplex conversation mode.",
                tags=["DUPLEX_MODE"],
            ),

            # ---- BACKGROUND BROWSER ----
            ToolDefinition(
                name="stop_background_browser",
                capability=Capability.BACKGROUND_BROWSER,
                description="Stop the background Playwright browser instance.",
                tags=["STOP_BACKGROUND_BROWSER"],
            ),

            # ---- OPEN CHATGPT ----
            ToolDefinition(
                name="open_chatgpt",
                capability=Capability.AI_CHAT,
                description="Open ChatGPT website and type/paste a query for the user. Smart tab reuse: if ChatGPT tab already exists, it will reuse it instead of opening a new tab.",
                parameters={"query": "string (the search query or prompt to type in ChatGPT)"},
                tags=["OPEN_CHATGPT", "OPEN_CHATAI"],
                requires_internet=True,
                examples=[
                    "OPEN_CHATGPT: latest AI news",
                    "OPEN_CHATGPT: make an image of sunset",
                ],
            ),

            # ---- OPEN CHATGPT NEW TAB ----
            ToolDefinition(
                name="open_chatgpt_new_tab",
                capability=Capability.AI_CHAT,
                description="Force open ChatGPT in a new tab, even if a ChatGPT tab already exists.",
                parameters={"query": "string (the search query or prompt to type in ChatGPT)"},
                tags=["OPEN_CHATGPT_NEW"],
                requires_internet=True,
                examples=[
                    "OPEN_CHATGPT_NEW: latest AI news",
                ],
            ),

            # ---- OPEN GEMINI ----
            ToolDefinition(
                name="open_gemini",
                capability=Capability.AI_CHAT,
                description="Open Google Gemini website and type/paste a query for the user. Smart tab reuse: if Gemini tab already exists, it will reuse it instead of opening a new tab.",
                parameters={"query": "string (the search query or prompt to type in Gemini)"},
                tags=["OPEN_GEMINI"],
                requires_internet=True,
                examples=[
                    "OPEN_GEMINI: Python tutorial",
                    "OPEN_GEMINI: summarize this article",
                ],
            ),

            # ---- OPEN GEMINI NEW TAB ----
            ToolDefinition(
                name="open_gemini_new_tab",
                capability=Capability.AI_CHAT,
                description="Force open Gemini in a new tab, even if a Gemini tab already exists.",
                parameters={"query": "string (the search query or prompt to type in Gemini)"},
                tags=["OPEN_GEMINI_NEW"],
                requires_internet=True,
                examples=[
                    "OPEN_GEMINI_NEW: Python tutorial",
                ],
            ),
        ]

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool definition by name."""
        return self._tools.get(name)

    def get_by_tag(self, tag: str) -> Optional[ToolDefinition]:
        """Get a tool definition by its concrete tag (e.g., 'FILE_SEARCH')."""
        return self._tag_map.get(tag.upper())

    def get_by_capability(self, capability: Capability) -> list[ToolDefinition]:
        """Get all tools for a given capability."""
        return self._capability_map.get(capability, [])

    def list_tools(self) -> list[ToolDefinition]:
        """List all registered tools."""
        return list(self._tools.values())

    def list_capabilities(self) -> list[Capability]:
        """List all registered capabilities."""
        return list(self._capability_map.keys())

    def list_tags(self) -> list[str]:
        """List all registered concrete tags."""
        return list(self._tag_map.keys())

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_tool_name(self, name: str) -> bool:
        """Check if a tool name is registered (rejects hallucinations)."""
        return name in self._tools

    def validate_capability_name(self, name: str) -> bool:
        """Check if a capability string name is registered.

        Args:
            name: capability name string (e.g., 'FILE_SEARCH', 'CHAT')

        Returns:
            True if the capability exists in the registry
        """
        try:
            cap = Capability[name.upper()]
            return cap in self._capability_map
        except (KeyError, ValueError):
            return False

    def validate_capability(self, capability: Capability) -> bool:
        """Check if a capability is registered."""
        return capability in self._capability_map

    def validate_tag(self, tag: str) -> bool:
        """Check if a tag is registered."""
        return tag.upper() in self._tag_map

    def validate_plan_tools(self, tool_names: list[str]) -> tuple[list[str], list[str]]:
        """Validate a list of tool names. Returns (valid, invalid)."""
        valid = []
        invalid = []
        for name in tool_names:
            if self.validate_tool_name(name):
                valid.append(name)
            else:
                invalid.append(name)
        return valid, invalid

    # ------------------------------------------------------------------
    # Capability → Tag mapping (for executor)
    # ------------------------------------------------------------------

    def get_tags_for_capability(self, capability: Capability) -> list[str]:
        """Get all concrete tags for a given capability."""
        tags = []
        for tool in self.get_by_capability(capability):
            tags.extend(tool.tags)
        return tags

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Return a summary of the registry for debugging."""
        return {
            "total_tools": len(self._tools),
            "total_capabilities": len(self._capability_map),
            "total_tags": len(self._tag_map),
            "capabilities": [c.name for c in self._capability_map.keys()],
            "tags": list(self._tag_map.keys()),
            "tool_names": list(self._tools.keys()),
        }

