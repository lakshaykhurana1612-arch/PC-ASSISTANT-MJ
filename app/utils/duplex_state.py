"""Global duplex state shared between TTS (speak) and duplex voice listener."""

from __future__ import annotations

_GLOBAL_DUPLEX_VOICE = None


def set_global_duplex_voice(v) -> None:
    global _GLOBAL_DUPLEX_VOICE
    _GLOBAL_DUPLEX_VOICE = v


def get_global_duplex_voice():
    return _GLOBAL_DUPLEX_VOICE

