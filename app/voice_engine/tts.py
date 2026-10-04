"""
Interruptible Text-to-Speech — Edge TTS backend.

Provides:
- Speak with preemption (new speech cuts off current)
- Backend-agnostic interface
- Dual voice support (Hindi/English)
- Queue-based speech for non-interrupt scenarios

Uses existing `edge_tts` but adds:
- Thread-safe stop/start
- is_speaking property
- on_start/on_finish callbacks (for ConversationManager)
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
import threading
import time
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import edge_tts

# Suppress pygame prompt
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import pygame

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class TTSConfig:
    voice_en: str = "en-IN-NeerjaNeural"
    voice_hi: str = "hi-IN-SwaraNeural"
    rate: str = "+25%"
    temp_audio_path: str = "mj_tts_temp.mp3"
    interruptible: bool = True  # Allow preemption


# ---------------------------------------------------------------------------
# TTS Engine
# ---------------------------------------------------------------------------


class InterruptibleTTS:
    """Thread-safe TTS engine with preemption support.

    Usage:
        tts = InterruptibleTTS()
        tts.speak("Hello Boss")           # Blocks until done or interrupted
        tts.speak("New command")           # Preempts previous speech
        tts.stop()                         # Immediate stop
        print(tts.is_speaking)             # Check state
    """

    def __init__(
        self,
        config: Optional[TTSConfig] = None,
        on_start: Optional[Callable] = None,
        on_finish: Optional[Callable] = None,
    ):
        self.config = config or TTSConfig()
        self._on_start = on_start
        self._on_finish = on_finish

        self._stop_event = threading.Event()
        self._speaking_lock = threading.Lock()
        self._is_speaking = False
        self._current_text = ""
        self._audio_ready = False

        # Initialize pygame mixer
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            self._audio_ready = True
        except pygame.error as e:
            logger.error(f"Audio output init failed: {e}")
            self._audio_ready = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking

    @property
    def current_text(self) -> str:
        return self._current_text

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    def speak(self, text: str) -> None:
        """Speak the given text. Interrupts any current speech if config allows.

        Args:
            text: text to speak aloud.
        """
        if not text or not text.strip():
            return

        # Clean text for speech
        spoken_text = self._clean_for_speech(text)
        if not spoken_text:
            return

        if not self._audio_ready:
            logger.warning("Audio output not available.")
            print(f"\nMJ: {text}\n")
            return

        # Stop current speech if interruptible
        if self.config.interruptible:
            self.stop()

        # Wait briefly for previous stop to complete
        time.sleep(0.05)

        with self._speaking_lock:
            self._is_speaking = True
            self._current_text = text
            self._stop_event.clear()

        # Notify start
        if self._on_start:
            try:
                self._on_start()
            except Exception as e:
                logger.error(f"on_start callback error: {e}")

        # Print to console
        print(f"\nMJ: {text}\n")

        # Pick voice
        voice = self.config.voice_hi if self._has_hindi(spoken_text) else self.config.voice_en

        # Use a unique temp path per call to avoid PermissionError collisions
        import tempfile as _tf
        fd, _tts_tmp = _tf.mkstemp(suffix=".mp3", prefix="mj_tts_")
        os.close(fd)
        temp_audio_path_str = str(_tts_tmp)

        try:
            # Generate audio
            async def generate():
                communicator = edge_tts.Communicate(
                    spoken_text, voice, rate=self.config.rate
                )
                await communicator.save(temp_audio_path_str)

            asyncio.run(generate())

            # Play audio (with stop-check loop)
            if self._stop_event.is_set():
                self._close_files(temp_audio_path_str)
                return

            pygame.mixer.music.load(temp_audio_path_str)
            pygame.mixer.music.play()

            while pygame.mixer.music.get_busy():
                if self._stop_event.is_set():
                    pygame.mixer.music.stop()
                    break
                pygame.time.Clock().tick(20)

        except Exception as e:
            logger.error(f"TTS playback error: {e}")
            # Try fallback voice
            fallback_voice = self.config.voice_en if voice == self.config.voice_hi else self.config.voice_hi
            try:

                async def retry():
                    comm = edge_tts.Communicate(spoken_text, fallback_voice, rate=self.config.rate)
                    await comm.save(temp_audio_path_str)

                asyncio.run(retry())

                if not self._stop_event.is_set():
                    pygame.mixer.music.load(temp_audio_path_str)
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy():
                        if self._stop_event.is_set():
                            pygame.mixer.music.stop()
                            break
                        pygame.time.Clock().tick(20)
            except Exception:
                pass

        finally:
            self._close_files(temp_audio_path_str)

    def stop(self) -> None:
        """Stop current speech immediately."""
        self._stop_event.set()
        try:
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
                try:
                    pygame.mixer.music.unload()
                except pygame.error:
                    pass
        except Exception:
            pass

    def _close_files(self, temp_audio_path: str) -> None:
        """Safe close of pygame audio + file cleanup for a given temp path."""
        # Release pygame audio
        try:
            if pygame.mixer.get_init():
                try:
                    pygame.mixer.music.stop()
                    pygame.mixer.music.unload()
                except pygame.error:
                    pass
        except Exception:
            pass

        # Delete temp file with retry
        _tp = Path(temp_audio_path)
        if _tp.exists():
            for attempt in range(3):
                try:
                    _tp.unlink()
                    break
                except PermissionError:
                    if attempt < 2:
                        time.sleep(0.1 * (attempt + 1))
                    else:
                        pass  # Windows still holding it, skip
                except Exception:
                    break

        # Reset speaking state
        with self._speaking_lock:
            self._is_speaking = False
            self._current_text = ""

        # Notify finish
        if self._on_finish:
            try:
                self._on_finish()
            except Exception as e:
                logger.error(f"on_finish callback error: {e}")

    def _cleanup(self):
        """Legacy cleanup — delegates to _close_files with empty path."""
        self._close_files("")

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _has_hindi(text: str) -> bool:
        """Check if text contains Devanagari (Hindi) characters."""
        return bool(re.search(r"[\u0900-\u097F]", text))

    @staticmethod
    def _clean_for_speech(text: str) -> str:
        """Remove formatting that should not be spoken."""
        text = re.sub(
            r"```.*?```", " I displayed the code on screen. ", text, flags=re.DOTALL
        )
        text = re.sub(r"https?://\S+", " link ", text)
        return (
            text.replace("`", "")
            .replace("*", "")
            .replace("#", "")
            .replace("_", " ")
            .strip()
        )

    def __del__(self):
        self.stop()

