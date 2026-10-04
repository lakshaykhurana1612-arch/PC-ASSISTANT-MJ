"""Duplex voice chat support for MJ.

This enables voice input even while MJ is speaking.

Implementation strategy:
- Background thread repeatedly calls listen() for short fixed duration.
- While TTS is active, transcripts are gated (ignored) for a short time
  after TTS start to reduce self-hearing.
- If a command is detected during that window, it will stop current
  pygame playback and immediately run the pipeline (on_command).

Note: True full-duplex requires audio echo cancellation; this is a
software safety compromise.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from app.utils.voice import listen
from app.utils.voice import pygame as _pygame  # type: ignore


@dataclass
class DuplexConfig:
    mic_poll_interval: float = 0.05
    min_gap_between_commands_sec: float = 1.2
    tts_echo_gate_sec: float = 1.0


class DuplexVoice:
    def __init__(
        self,
        on_command: Callable[[str], None],
        config: DuplexConfig | None = None,
    ):

        self.on_command = on_command
        self.config = config or DuplexConfig()

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._tts_lock = threading.Lock()
        self._tts_active = False
        self._tts_started_at: float | None = None

        self._last_command_at = 0.0

    def mark_tts_started(self) -> None:
        with self._tts_lock:
            self._tts_active = True
            self._tts_started_at = time.time()

    def mark_tts_finished(self) -> None:
        with self._tts_lock:
            self._tts_active = False

    def _should_ignore_transcript(self) -> bool:
        with self._tts_lock:
            if not self._tts_active:
                return False
            if self._tts_started_at is None:
                return True
            return (time.time() - self._tts_started_at) <= self.config.tts_echo_gate_sec

    def _stop_tts_playback(self) -> None:
        try:
            if hasattr(_pygame, "mixer") and _pygame.mixer.get_init():
                try:
                    _pygame.mixer.music.stop()
                except Exception:
                    pass
                # Unload to release the file handle on Windows
                try:
                    _pygame.mixer.music.unload()
                except Exception:
                    pass
        except Exception:
            pass

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()

        # Keyboard interrupt: press ANY key to stop current TTS playback.
        try:
            import keyboard  # type: ignore

            def _on_any_key(_event=None):
                # Stop only (do not trigger new command). This matches your request
                # "speak start karti hai for nhi rukti".
                self._stop_tts_playback()

            # Register a universal hotkey for any key down.
            # keyboard hooks return a handle that we can remove in stop().
            self._keyboard_hook = keyboard.hook(_on_any_key)
        except Exception:
            self._keyboard_hook = None

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()


    def stop(self) -> None:
        self._stop_event.set()
        try:
            hk = getattr(self, "_keyboard_hook", None)
            if hk is not None:
                import keyboard  # type: ignore

                keyboard.unhook(hk)
        except Exception:
            pass


    def _loop(self) -> None:
        while not self._stop_event.is_set():
            text = listen()
            if not text:
                time.sleep(self.config.mic_poll_interval)
                continue

            text = text.strip()
            if not text:
                continue

            if self._should_ignore_transcript():
                continue

            now = time.time()
            if now - self._last_command_at < self.config.min_gap_between_commands_sec:
                continue
            self._last_command_at = now

            # Interrupt current TTS and run new command
            self._stop_tts_playback()
            self.mark_tts_finished()
            try:
                self.on_command(text)

            except Exception:
                pass

