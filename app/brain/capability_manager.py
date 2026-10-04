"""
Capability Manager — Interface layer between Planner and Executor.

The Planner works with abstract Capabilities (not concrete tags).
The CapabilityManager resolves capabilities to available tools and
provides capability definitions for the LLM prompt.

This is the key abstraction that keeps the Planner decoupled from
concrete tag implementations. New tools can be added to the
ToolRegistry without changing the Planner.

Usage:
    mgr = CapabilityManager.get_instance()
    caps = mgr.get_available_capabilities()
    tools = mgr.resolve_capability(Capability.WEB_SEARCH)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from app.brain.tool_registry import ToolRegistry, Capability, ToolDefinition

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Capability descriptor (for LLM prompt generation)
# ---------------------------------------------------------------------------


@dataclass
class CapabilityDescriptor:
    """Human-readable description of a capability for the LLM."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    examples: list[str] = field(default_factory=list)
    requires_internet: bool = False
    requires_approval: bool = False


# ---------------------------------------------------------------------------
# Capability Manager (Singleton)
# ---------------------------------------------------------------------------


class CapabilityManager:
    """Manages capabilities and resolves them to tools.

    Singleton pattern.
    """

    _instance: Optional["CapabilityManager"] = None

    def __init__(self):
        self._registry = ToolRegistry.get_instance()
        # Cache capability descriptors
        self._descriptors: dict[Capability, CapabilityDescriptor] = {}
        self._build_descriptors()

    @classmethod
    def get_instance(cls) -> "CapabilityManager":
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _build_descriptors(self) -> None:
        """Build capability descriptors from the tool registry."""
        for capability in Capability:
            tools = self._registry.get_by_capability(capability)
            if not tools:
                continue

            # Combine descriptions from all tools in this capability
            descriptions = [t.description for t in tools if t.description]
            primary_desc = descriptions[0] if descriptions else f"Perform {capability.name} operations."

            # Collect parameters
            params: dict[str, Any] = {}
            for t in tools:
                params.update(t.parameters)

            # Collect examples
            examples: list[str] = []
            for t in tools:
                examples.extend(t.examples)

            # Requirements
            requires_internet = any(t.requires_internet for t in tools)
            requires_approval = any(t.requires_approval for t in tools)

            self._descriptors[capability] = CapabilityDescriptor(
                name=capability.name.lower(),
                description=primary_desc,
                parameters=params,
                examples=examples[:5],  # Limit examples
                requires_internet=requires_internet,
                requires_approval=requires_approval,
            )

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get_available_capabilities(self) -> list[Capability]:
        """Get all registered capabilities."""
        return self._registry.list_capabilities()

    def get_descriptor(self, capability: Capability) -> Optional[CapabilityDescriptor]:
        """Get the descriptor for a capability."""
        return self._descriptors.get(capability)

    def get_all_descriptors(self) -> dict[str, CapabilityDescriptor]:
        """Get all capability descriptors keyed by name."""
        return {
            c.name.lower(): d
            for c, d in self._descriptors.items()
        }

    def resolve_capability(self, capability: Capability) -> list[ToolDefinition]:
        """Resolve a capability to its concrete tools."""
        return self._registry.get_by_capability(capability)

    def capability_from_intent(self, intent_name: str) -> Optional[Capability]:
        """Map an intent name (from IntentRouter) to a Capability.

        Args:
            intent_name: string like 'chat', 'search', 'file'

        Returns:
            Capability enum or None if not found
        """
        mapping = {
            "chat": Capability.CHAT,
            "search": Capability.WEB_SEARCH,
            "browser": Capability.WEB_BROWSER,
            "file": Capability.FILE_SEARCH,
            "file_read": Capability.FILE_READ,
            "file_move": Capability.FILE_MOVE,
            "file_delete": Capability.FILE_DELETE,
            "whatsapp": Capability.WHATSAPP_MESSAGE,
            "whatsapp_file": Capability.WHATSAPP_FILE,
            "whatsapp_bg": Capability.WHATSAPP_BACKGROUND,
            "system": Capability.SYSTEM_CONTROL,
            "app": Capability.APP_LAUNCH,
            "tab": Capability.TAB_MANAGE,
            "developer": Capability.PROJECT_ANALYZE,
            "vision": Capability.SCREEN_CAPTURE,
            "mode": Capability.MODE_SWITCH,
            "background_browser": Capability.BACKGROUND_BROWSER,
        }
        return mapping.get(intent_name.lower())

    # ------------------------------------------------------------------
    # Summary for LLM prompts
    # ------------------------------------------------------------------

    def get_capabilities_prompt_block(self) -> str:
        """Generate a capabilities summary block for the LLM system prompt.

        Returns a formatted string describing all available capabilities.
        """
        lines = ["AVAILABLE CAPABILITIES:"]
        for cap in sorted(self.get_available_capabilities(), key=lambda c: c.name):
            desc = self.get_descriptor(cap)
            if not desc:
                continue

            cap_line = f"  - {desc.name}: {desc.description}"
            if desc.requires_internet:
                cap_line += " [requires internet]"
            if desc.requires_approval:
                cap_line += " [requires approval]"
            lines.append(cap_line)

            if desc.parameters:
                for param_name, param_desc in desc.parameters.items():
                    lines.append(f"      param: {param_name} = {param_desc}")

        return "\n".join(lines)

    def summary(self) -> dict[str, Any]:
        """Return summary for debugging."""
        return {
            "total_capabilities": len(self._descriptors),
            "capabilities": list(self._descriptors.keys()),
        }

