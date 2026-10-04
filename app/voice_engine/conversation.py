"""
ConversationManager — Thin wrapper around VoiceAssistant.

Provides a simplified interface for managing voice conversation modes.
This is a compatibility layer that delegates to VoiceAssistant.

Usage:
    manager = ConversationManager(on_command=my_callback)
    manager.start_duplex()       # Start voice assistant
    manager.stop()               # Stop everything
    manager.speak("Hello")       # TTS output
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from app.voice_engine.voice_assistant import (
    VoiceAssistant,
    VoiceAssistantConfig,
    AssistantState,
)

logger = logging.getLogger(__name__)


@dataclass
class ConversationConfig:
    """Configuration for ConversationManager (compatibility layer)."""

    mode: str = "duplex"  # Always duplex (classic/streaming removed)
    sample_rate: int = 16000
    max_speech_duration: float = 10.0
    silence_timeout_ms: int = 600
    vad_threshold: float = 0.3
    tts_voice_en: str = "en-IN-NeerjaNeural"
    tts_voice_hi: str = "hi-IN-SwaraNeural"
    wake_words: list[str] = field(default_factory=lambda: ["mj"])


class ConversationManager:
    """Simplified conversation manager backed by VoiceAssistant.

    Usage:
        manager = ConversationManager(on_command=my_callback)
        manager.start_duplex()
        ...
        manager.stop()
    """

    def __init__(
        self,
        on_command: Optional[Callable[[str], None]] = None,
        on_state_change: Optional[Callable] = None,
        on_event: Optional[Callable] = None,
        config: Optional[ConversationConfig] = None,
    ):
        self.on_command = on_command
        self.on_state_change = on_state_change
        self.on_event = on_event
        self.config = config or ConversationConfig()

        # Build VoiceAssistant config
        assistant_config = VoiceAssistantConfig(
            wake_word=self.config.wake_words[0] if self.config.wake_words else "mj",
            vad_mode=1,
            min_speech_duration_ms=200,
            min_silence_duration_ms=self.config.silence_timeout_ms,
            max_record_seconds=int(self.config.max_speech_duration),
            conversation_timeout_seconds=15.0,
            sample_rate=self.config.sample_rate,
            voice_en=self.config.tts_voice_en,
            voice_hi=self.config.tts_voice_hi,
        )

        # Create VoiceAssistant
        self._assistant = VoiceAssistant(
            on_command=self._on_command,
            on_wake=self._on_wake,
            config=assistant_config,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self):
        return self._assistant.state

    @property
    def is_duplex_running(self) -> bool:
        return self._assistant.in_conversation

    # ------------------------------------------------------------------
    # Internal callbacks
    # ------------------------------------------------------------------

    def _on_wake(self):
        """Wake word detected."""
        logger.info("Wake word detected")
        if self.on_event:
            try:
                self.on_event("wake_detected")
            except Exception:
                pass

    def _on_command(self, text: str):
        """Command from VoiceAssistant."""
        if self.on_command:
            try:
                self.on_command(text)
            except Exception as e:
                logger.error(f"Command callback error: {e}")

        if self.on_event:
            try:
                self.on_event("transcript", text)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def listen_classic(self, duration: float = 6.0):
        """Backward-compatible classic listen (not used in new system)."""
        from app.voice_engine.recorder import StreamingRecorder
        from app.voice_engine.stt import AutoSTT

        recorder = StreamingRecorder()
        audio = recorder.record_fixed(duration)
        if audio is None:
            return None
        stt = AutoSTT()
        return stt.transcribe(audio, self.config.sample_rate)

    def listen_streaming(self):
        """Backward-compatible streaming listen (delegates to assistant)."""
        # In the new system, VoiceAssistant handles everything.
        # This is here for API compatibility.
        return self.listen_classic()

    def start_duplex(self):
        """Start duplex/conversation mode (non-blocking)."""
        self._assistant.start()
        # Force conversation mode
        self._assistant._is_conversation = True
        self._assistant.state = AssistantState.LISTENING
        logger.info("Duplex conversation mode started")

    def stop_duplex(self):
        """Stop duplex mode."""
        self._assistant.force_exit_conversation()
        logger.info("Duplex conversation mode stopped")

    def speak(self, text: str) -> None:
        """Speak text (blocking, delegates to assistant TTS)."""
        # Print to console
        print(f"\nMJ: {text}\n")
        self._assistant.speak(text)

    def stop_speaking(self) -> None:
        """Stop current speech."""
        self._assistant._stop_tts()

    def start_classic_listener(self):
        """Start classic listener (backward compat, uses VoiceAssistant)."""
        self._assistant.start()
        # Don't force conversation — stays in wake word mode
        logger.info("Classic listener started")

    def stop(self):
        """Stop all activity."""
        self._assistant.stop()

    def pause(self):
        """Pause listening."""
        self._assistant.state = AssistantState.IDLE
        self._assistant._is_conversation = False

    def resume(self):
        """Resume listening."""
        self._assistant.start()

    def __del__(self):
        self.stop()
