from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Session:
    """Runtime session state.

    This is intentionally minimal to avoid breaking current behavior.
    Future: store per-user conversation memory, config flags, and security state.
    """

    attributes: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.attributes.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.attributes[key] = value

