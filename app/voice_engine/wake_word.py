"""
Wake Word Detection — Lightweight VAD + keyword approach.

Uses webrtcvad for speech activity detection + Google STT to transcribe
short speech segments and check for the wake word.

No heavy ML models (no torch, no openwakeword).
Works with a shared audio source (single sounddevice InputStream).

Usage:
    detector = WakeWordDetector(on_wake=my_callback)
    detector.start()
    ...
    detector.stop()

The detector runs a lightweight background thread that:
1. Captures short audio segments (1.5s) periodically
2. Runs VAD to check if there's speech
3. If speech detected, transcribes via Google STT
4. If transcript contains wake word → fires callback
"""

from __future__ import annotations

import io
import logging
import threading
import time
import wave
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class WakeWordConfig:
    """Configuration for wake word detection."""

    wake_word: str = "mj"
    sample_rate: int = 16000
    listen_duration: float = 1.5  # Seconds per listen cycle
    cooldown_seconds: float = 2.0  # Prevent re-trigger
    energy_threshold: int = 300  # For speech_recognition


# ---------------------------------------------------------------------------
# WakeWordDetector
# ---------------------------------------------------------------------------


class WakeWordDetector:
    """Lightweight wake word detector using VAD + Google STT.

    Listens in short bursts, transcribes when speech detected,
    checks for wake word in transcript.

    Usage:
        detector = WakeWordDetector(on_wake=my_callback)
        detector.start()
        ...
        detector.stop()
    """

    def __init__(
        self,
        on_wake: Optional[Callable] = None,
        on_transcript: Optional[Callable[[str], None]] = None,
        config: Optional[WakeWordConfig] = None,
    ):
        self.on_wake = on_wake
        self.on_transcript = on_transcript
        self.config = config or WakeWordConfig()

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False
        self._last_wake_time = 0.0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_available(self) -> bool:
        """This detector is always available (only needs speech_recognition)."""
        try:
            import speech_recognition
            return True
        except ImportError:
            return False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """Start wake word detection in background thread."""
        if self._running:
            logger.warning("Wake word detector already running.")
            return

        if not self.is_available:
            logger.error("speech_recognition not installed.")
            return

        self._stop_event.clear()
        self._running = True

        self._thread = threading.Thread(target=self._detection_loop, daemon=True)
        self._thread.start()
        logger.info("Wake word detector started (VAD + keyword).")

    def _detection_loop(self):
        """Background loop: listen in short bursts, check for wake word."""
        import speech_recognition as sr

        recognizer = sr.Recognizer()
        recognizer.energy_threshold = self.config.energy_threshold

        # Get default microphone
        try:
            microphone = sr.Microphone()
        except Exception as e:
            logger.error(f"Microphone error: {e}")
            self._running = False
            return

        # Calibrate once
        try:
            with microphone as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                logger.info("Microphone calibrated.")
        except Exception as e:
            logger.error(f"Calibration error: {e}")
            self._running = False
            return

        consecutive_errors = 0

        while not self._stop_event.is_set():
            try:
                # Listen in short burst
                with microphone as source:
                    audio = recognizer.listen(
                        source,
                        timeout=1.0,
                        phrase_time_limit=2.0,
                    )

                # Got audio — transcribe
                try:
                    text = recognizer.recognize_google(audio).strip().lower()
                except sr.UnknownValueError:
                    # Audio but no speech recognized — skip
                    consecutive_errors = 0
                    time.sleep(0.1)
                    continue
                except sr.RequestError as e:
                    logger.error(f"STT request error: {e}")
                    consecutive_errors += 1
                    if consecutive_errors > 5:
                        time.sleep(2)
                    continue

                consecutive_errors = 0

                if not text:
                    continue

                logger.debug(f"Heard: '{text}'")

                # Check for wake word
                if self._check_wake_word(text):
                    self._on_wake_detected(text)

            except sr.WaitTimeoutError:
                # No audio detected — normal idle
                consecutive_errors = 0
                pass
            except Exception as e:
                logger.error(f"Detection loop error: {e}")
                consecutive_errors += 1
                if consecutive_errors > 10:
                    logger.warning("Too many errors, pausing...")
                    time.sleep(3)
                    consecutive_errors = 0

        self._running = False

    def _check_wake_word(self, text: str) -> bool:
        """Check if transcript contains the wake word."""
        wake = self.config.wake_word.lower()
        t = text.lower().strip()

        # Also check common variations
        wake_variants = {wake, "m j", "em jay", "m. j." , "mg" , "MJ" }

        # Check if transcript starts with wake word
        for variant in wake_variants:
            if t.startswith(variant):
                # Check cooldown
                now = time.time()
                if now - self._last_wake_time >= self.config.cooldown_seconds:
                    self._last_wake_time = now
                    return True

        # Check first word
        words = t.split()
        if words and words[0] in wake_variants:
            now = time.time()
            if now - self._last_wake_time >= self.config.cooldown_seconds:
                self._last_wake_time = now
                return True

        return False

    def _on_wake_detected(self, full_text: str):
        """Handle wake word detection."""
        logger.info(f"Wake word detected in: '{full_text}'")

        # Extract command after wake word
        wake = self.config.wake_word.lower()
        t = full_text.lower().strip()
        command = ""

        if t.startswith(wake):
            command = t[len(wake):].strip()
        elif len(t.split()) > 1:
            command = " ".join(t.split()[1:])

        # Fire callbacks
        if self.on_wake:
            try:
                self.on_wake()
            except Exception as e:
                logger.error(f"on_wake callback error: {e}")

        if self.on_transcript and command:
            try:
                self.on_transcript(command)
            except Exception as e:
                logger.error(f"on_transcript callback error: {e}")

    def stop(self):
        """Stop wake word detection."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._running = False
        logger.info("Wake word detector stopped.")

    def __del__(self):
        self.stop()

