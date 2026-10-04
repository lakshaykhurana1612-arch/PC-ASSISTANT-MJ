"""
VoiceAssistant — Unified voice assistant like ChatGPT/Gemini Voice.

Architecture:
    One sounddevice InputStream (non-blocking) runs continuously.
    A processing thread reads audio chunks and runs VAD (webrtcvad).
    When speech segment is detected → recorded from start to silence end.
    Speech segment → Google STT → callback → AI pipeline → TTS.

Features:
- Always-on VAD-based listening (background thread, single InputStream)
- Wake word "mj" activation
- Continuous conversation mode after wake
- Natural interrupt (speak over TTS → stops TTS, processes new command)
- Instant capture from speech start to silence end (no fixed recording)
- 30s idle timeout in conversation mode
- "bye" / "thank you" to exit conversation mode
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import tempfile
import threading
import time
import wave
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

import numpy as np

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import pygame

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
# webrtcvad requires exactly 30ms frames → 480 samples → 960 bytes at 16kHz
BLOCKSIZE = 480  # 480 samples = 960 bytes = 30ms at 16kHz (webrtcvad requirement)
VAD_FRAME_MS = 30

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class AssistantState(Enum):
    IDLE = auto()            # Waiting for wake word
    ACTIVATED = auto()       # Wake word heard, entering conversation
    LISTENING = auto()       # Waiting for speech segment
    CAPTURING = auto()       # Recording speech (VAD says speaking)
    PROCESSING = auto()      # Transcribing + AI pipeline
    SPEAKING = auto()        # TTS playback active
    INTERRUPTED = auto()     # User spoke over TTS → processing new command


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class VoiceAssistantConfig:
    """Configuration for VoiceAssistant."""

    # Wake word
    wake_word: str = "mj"
    wake_sensitivity: float = 0.3  # Lower = more sensitive to wake

    # VAD
    vad_mode: int = 1  # 0=aggressive, 3=least aggressive (webrtcvad mode)
    min_speech_duration_ms: int = 200   # Min speech to accept
    min_silence_duration_ms: int = 600  # Silence before speech considered ended
    max_record_seconds: float = 10.0     # Max recording per utterance

    # Conversation
    conversation_timeout_seconds: float = 15.0  # Silence timeout in conversation mode
    cooldown_after_tts: float = 1.0  # Pause after TTS before listening (echo prevention)

    # Audio
    sample_rate: int = SAMPLE_RATE
    blocksize: int = BLOCKSIZE
    input_device: Optional[int] = None

    # TTS
    voice_en: str = "en-IN-NeerjaNeural"
    voice_hi: str = "hi-IN-SwaraNeural"
    tts_rate: str = "+25%"


# ---------------------------------------------------------------------------
# VoiceAssistant
# ---------------------------------------------------------------------------


class VoiceAssistant:
    """Unified voice assistant that works like ChatGPT/Gemini voice.

    Usage:
        assistant = VoiceAssistant(on_command=my_callback)
        assistant.start()
        ...
        assistant.stop()
    """

    def __init__(
        self,
        on_command: Callable[[str], None],
        on_wake: Optional[Callable] = None,
        config: Optional[VoiceAssistantConfig] = None,
    ):
        self.on_command = on_command
        self.on_wake = on_wake
        self.config = config or VoiceAssistantConfig()

        # State
        self._state = AssistantState.IDLE
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()

        # Audio stream
        self._stream = None
        self._audio_buffer: list[np.ndarray] = []
        self._buffer_lock = threading.Lock()
        self._capture_buffer: list[np.ndarray] = []  # Current speech capture

        # VAD
        self._vad = None
        self._speech_detected = False
        self._silence_frames = 0
        self._speech_frames = 0
        self._in_speech = False

        # Conversation
        self._last_speech_time = 0.0
        self._last_tts_time = 0.0
        self._is_conversation = False  # In continuous conversation mode

        # Threads
        self._process_thread: Optional[threading.Thread] = None
        self._audio_thread: Optional[threading.Thread] = None

        # TTS
        self._tts_stop = threading.Event()
        self._tts_active = False
        self._pygame_ready = False
        self._init_pygame()

        # Wake word counter
        self._wake_attempts = 0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> AssistantState:
        with self._state_lock:
            return self._state

    @state.setter
    def state(self, new_state: AssistantState):
        with self._state_lock:
            old = self._state
            self._state = new_state
            if old != new_state:
                logger.debug(f"State: {old.name} → {new_state.name}")

    @property
    def is_running(self) -> bool:
        return not self._stop_event.is_set()

    @property
    def in_conversation(self) -> bool:
        return self._is_conversation

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def _init_pygame(self):
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            self._pygame_ready = True
        except Exception as e:
            logger.warning(f"pygame init failed: {e}")
            self._pygame_ready = False

    def _init_vad(self):
        """Initialize webrtcvad."""
        if self._vad is not None:
            return True
        try:
            import webrtcvad
            self._vad = webrtcvad.Vad(self.config.vad_mode)
            logger.info("webrtcvad initialized (mode=%d)", self.config.vad_mode)
            return True
        except ImportError:
            logger.warning("webrtcvad not installed. Install: pip install webrtcvad")
            return False
        except Exception as e:
            logger.error(f"VAD init error: {e}")
            return False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Start the voice assistant (background threads).

        Returns:
            True if started successfully, False otherwise.
        """
        if self._process_thread and self._process_thread.is_alive():
            logger.warning("VoiceAssistant already running")
            return True  # Already running is not a failure

        if not self._init_vad():
            logger.error("VAD initialization failed — cannot start")
            return False

        self._stop_event.clear()
        self.state = AssistantState.IDLE
        self._is_conversation = False
        self._last_speech_time = time.time()  # Prevent immediate timeout

        # Start audio stream thread
        self._audio_thread = threading.Thread(target=self._audio_loop, daemon=True)
        self._audio_thread.start()

        # Start processing thread
        self._process_thread = threading.Thread(target=self._process_loop, daemon=True)
        self._process_thread.start()

        logger.info("VoiceAssistant started (IDLE - waiting for wake word)")
        return True

    def start_conversation(self) -> bool:
        """Start the voice assistant and immediately enter conversation mode.

        This is an atomic operation to avoid the state gap between start()
        and manually setting _is_conversation + state from outside.

        Returns:
            True if started successfully, False otherwise.
        """
        if not self.start():
            return False
        # Atomically enter conversation mode after VAD init + threads started
        self._is_conversation = True
        self._last_speech_time = time.time()
        self.state = AssistantState.LISTENING
        logger.info("VoiceAssistant started in CONVERSATION mode (LISTENING)")
        return True

    def stop(self):
        """Stop the voice assistant."""
        self._stop_event.set()
        self._stop_tts()

        # Close stream
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        # Join threads
        for t in [self._audio_thread, self._process_thread]:
            if t and t.is_alive():
                t.join(timeout=2)

        self.state = AssistantState.IDLE
        logger.info("VoiceAssistant stopped")

    # ------------------------------------------------------------------
    # Audio Loop (continuous InputStream)
    # ------------------------------------------------------------------

    def _audio_loop(self):
        """Background: run sounddevice InputStream.
        
        This thread ONLY runs the InputStream. Audio processing is done
        by _process_loop to avoid race conditions.
        """
        import sounddevice as sd

        try:
            with sd.InputStream(
                samplerate=self.config.sample_rate,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=self.config.blocksize,
                device=self.config.input_device,
                callback=self._audio_callback,
            ):
                self._stop_event.wait()  # Block until stop is signaled
        except Exception as e:
            logger.error(f"Audio stream error: {e}")

    def _audio_callback(self, indata, frames, time_info, status):
        """sounddevice callback — fills shared buffer."""
        if status:
            logger.warning(f"Audio status: {status}")

        # Copy data and push to shared buffer
        with self._buffer_lock:
            self._audio_buffer.append(indata.copy().flatten())

    def _flush_audio_buffer(self):
        """Process accumulated audio from the buffer."""
        chunks = []
        with self._buffer_lock:
            if not self._audio_buffer:
                return
            chunks = self._audio_buffer.copy()
            self._audio_buffer.clear()

        for chunk in chunks:
            self._process_audio_chunk(chunk)

    # ------------------------------------------------------------------
    # VAD + Speech Detection
    # ------------------------------------------------------------------

    def _process_audio_chunk(self, chunk: np.ndarray):
        """Process a single audio chunk: VAD + speech capture."""
        # Convert to bytes for webrtcvad
        if chunk.dtype != np.int16:
            chunk = (chunk * 32768).astype(np.int16)
        audio_bytes = chunk.tobytes()

        # VAD check (webrtcvad requires 30ms frames = 480 bytes at 16kHz)
        try:
            is_speech = self._vad.is_speech(audio_bytes, self.config.sample_rate)
        except Exception:
            # If frame size mismatch, skip VAD
            return

        # Current state determines how we handle VAD results
        current_state = self.state

        # During SPEAKING state: ignore ALL mic input to prevent TTS echo
        # (speaker output picked up by mic) from triggering accidental commands.
        # Interrupt is disabled because we can't distinguish user speech from TTS echo.
        # User can wait for TTS to finish and then speak.
        if current_state == AssistantState.SPEAKING:
            return

        # Check post-TTS echo cooldown: ignore mic input for a period after TTS
        # to let speaker echo die down before processing new speech
        cooldown_remaining = self._last_tts_time + self.config.cooldown_after_tts - time.time()
        if cooldown_remaining > 0:
            return  # Still in cooldown after TTS (echo bleed prevention)

        # If in conversation or capturing, always process speech
        if current_state in (AssistantState.LISTENING, AssistantState.CAPTURING) or self._is_conversation:
            self._handle_speech_capture(chunk, is_speech)
        elif current_state == AssistantState.IDLE:
            self._handle_wake_detection(chunk, is_speech)
        elif current_state == AssistantState.INTERRUPTED:
            self._handle_speech_capture(chunk, is_speech)

    # ------------------------------------------------------------------
    # Wake Word Detection
    # ------------------------------------------------------------------

    def _handle_wake_detection(self, chunk: np.ndarray, is_speech: bool):
        """In IDLE mode: detect speech segment, transcribe, check for wake word."""
        if is_speech:
            self._capture_buffer.append(chunk)
            self._silence_frames = 0
            self._speech_frames += 1
        elif self._speech_frames > 0:
            self._silence_frames += 1
            # Still appending during trailing silence
            self._capture_buffer.append(chunk)

            silence_frames_needed = int(
                self.config.min_silence_duration_ms / VAD_FRAME_MS
            )
            if self._silence_frames >= silence_frames_needed:
                # Speech segment complete — check for wake word
                self._check_wake_word()
                self._capture_buffer.clear()
                self._speech_frames = 0
                self._silence_frames = 0
        else:
            # Not speech, no speech in progress — discard
            pass

        # Safety: discard if too long
        if len(self._capture_buffer) * VAD_FRAME_MS > 3000:  # 3s max for wake check
            self._capture_buffer.clear()
            self._speech_frames = 0
            self._silence_frames = 0

    def _check_wake_word(self):
        """Transcribe captured audio and check for wake word."""
        if not self._capture_buffer:
            return

        audio = np.concatenate(self._capture_buffer)
        text = self._transcribe(audio)
        if not text:
            return

        text = text.lower().strip()
        wake = self.config.wake_word.lower()

        # Check if transcript starts with wake word
        if text.startswith(wake) or text.startswith(wake + " ") or text == wake:
            logger.info(f"Wake word detected: '{wake}' in '{text}'")
            self._on_wake_detected(text[len(wake):].strip())
        else:
            # Try partial match with low threshold
            words = text.split()
            if words and words[0] == wake:
                logger.info(f"Wake word detected (first word): '{wake}'")
                self._on_wake_detected(" ".join(words[1:]))

    def _on_wake_detected(self, command: str):
        """Handle successful wake word detection."""
        self.state = AssistantState.ACTIVATED
        self._is_conversation = True
        self._last_speech_time = time.time()

        # Callback
        if self.on_wake:
            try:
                self.on_wake()
            except Exception as e:
                logger.error(f"on_wake callback error: {e}")

        # If there's a command after wake word, process it
        if command:
            self.state = AssistantState.PROCESSING
            try:
                self.on_command(command)
            except Exception as e:
                logger.error(f"Command callback error: {e}")
            self.state = AssistantState.LISTENING
        else:
            self.state = AssistantState.LISTENING

    # ------------------------------------------------------------------
    # Speech Capture (Conversation Mode)
    # ------------------------------------------------------------------

    def _handle_speech_capture(self, chunk: np.ndarray, is_speech: bool):
        """In conversation/listening mode: capture speech until silence."""
        # Update conversation timeout
        if is_speech:
            self._last_speech_time = time.time()

        if is_speech:
            # Start of speech or continuing speech
            if not self._in_speech:
                self._in_speech = True
                self._capture_buffer.clear()
                self.state = AssistantState.CAPTURING
                logger.debug("Speech started — capturing")

            self._capture_buffer.append(chunk)
            self._silence_frames = 0
            self._speech_frames += 1

        elif self._in_speech:
            # Silence after speech — append during trailing silence
            self._capture_buffer.append(chunk)
            self._silence_frames += 1

            silence_frames_needed = int(
                self.config.min_silence_duration_ms / VAD_FRAME_MS
            )
            if self._silence_frames >= silence_frames_needed:
                # Speech segment complete
                self._finalize_speech()
                self._in_speech = False
                self._capture_buffer.clear()
                self._speech_frames = 0
                self._silence_frames = 0

    def _finalize_speech(self):
        """Process captured speech segment."""
        if not self._capture_buffer:
            self.state = AssistantState.LISTENING if self._is_conversation else AssistantState.IDLE
            return

        audio = np.concatenate(self._capture_buffer)
        min_samples = self.config.sample_rate * self.config.min_speech_duration_ms // 1000
        if len(audio) < min_samples:
            logger.debug("Speech too short, ignoring")
            self.state = AssistantState.LISTENING if self._is_conversation else AssistantState.IDLE
            return

        self.state = AssistantState.PROCESSING
        logger.debug(f"Speech captured: {len(audio)/self.config.sample_rate:.1f}s")

        text = self._transcribe(audio)
        if text:
            text = text.strip()
            logger.info(f"Transcribed: '{text}'")

            # Check for exit commands
            if self._is_conversation and text.lower() in (
                "bye", "bye bye", "goodbye", "exit", "stop", "thank you", "thanks"
            ):
                self._exit_conversation()
                return

            # Process command
            try:
                self.on_command(text)
            except Exception as e:
                logger.error(f"Command callback error: {e}")

        # Go back to listening (conversation) or idle
        if self._is_conversation:
            # Check timeout
            if time.time() - self._last_speech_time > self.config.conversation_timeout_seconds:
                logger.info("Conversation timeout — returning to IDLE")
                self._is_conversation = False
                self.state = AssistantState.IDLE
            else:
                self.state = AssistantState.LISTENING
        else:
            self.state = AssistantState.IDLE

    # ------------------------------------------------------------------
    # Interrupt Handling (User speaks over TTS)
    # ------------------------------------------------------------------

    def _handle_interrupt(self, chunk: np.ndarray):
        """User spoke while TTS was playing — interrupt and capture."""
        logger.info("User interrupt detected! Stopping TTS.")
        self._stop_tts()

        self.state = AssistantState.INTERRUPTED
        self._in_speech = True
        self._capture_buffer.clear()
        self._capture_buffer.append(chunk)
        self._silence_frames = 0
        self._speech_frames = 1

    # ------------------------------------------------------------------
    # TTS
    # ------------------------------------------------------------------

    def speak(self, text: str) -> None:
        """Speak text (non-blocking for the assistant, but blocks here)."""
        if not text or not text.strip():
            return

        # Reset ALL speech capture state before entering SPEAKING to prevent
        # stale echo/timing issues. This is critical: if VAD detected speech
        # in the window between start_conversation and this speak() call,
        # _in_speech would be True and _capture_buffer would have audio.
        # During SPEAKING, that audio would sit in the buffer. After TTS,
        # it would be transcribed and could trigger accidental exit commands.
        self._in_speech = False
        self._capture_buffer.clear()
        self._speech_frames = 0
        self._silence_frames = 0

        self.state = AssistantState.SPEAKING
        self._tts_active = True
        self._tts_stop.clear()

        try:
            self._speak_edge_tts(text)
        finally:
            self._tts_active = False
            self._last_tts_time = time.time()

            # Also reset speech state after TTS to avoid stale buffer issues
            self._in_speech = False
            self._capture_buffer.clear()
            self._speech_frames = 0
            self._silence_frames = 0

            # After TTS, check if we should go back to listening
            if not self._stop_event.is_set():
                if self._is_conversation:
                    self.state = AssistantState.LISTENING
                else:
                    self.state = AssistantState.IDLE

    def _speak_edge_tts(self, text: str):
        """Generate and play TTS audio using edge-tts + pygame."""
        import edge_tts

        if not self._pygame_ready:
            logger.warning("Audio output not available")
            print(f"\nMJ: {text}\n")
            return

        # Clean text
        clean = self._clean_text(text)
        if not clean:
            return

        # Pick voice
        has_hindi = bool(__import__('re').search(r'[\u0900-\u097F]', clean))
        voice = self.config.voice_hi if has_hindi else self.config.voice_en

        # Use unique temp path per call to avoid PermissionError collisions
        import tempfile as _tf
        fd, temp_path = _tf.mkstemp(suffix=".mp3", prefix="mj_va_tts_")
        os.close(fd)
        temp_path = str(temp_path)

        try:
            # Generate
            async def _gen():
                comm = edge_tts.Communicate(clean, voice, rate=self.config.tts_rate)
                await comm.save(temp_path)

            asyncio.run(_gen())

            # Check if stopped during generation
            if self._tts_stop.is_set() or self._stop_event.is_set():
                self._cleanup_tts(temp_path)
                return

            # Play
            pygame.mixer.music.load(temp_path)
            pygame.mixer.music.play()

            while pygame.mixer.music.get_busy():
                if self._tts_stop.is_set() or self._stop_event.is_set():
                    pygame.mixer.music.stop()
                    break
                pygame.time.Clock().tick(20)

        except Exception as e:
            logger.error(f"TTS error: {e}")
            # Try fallback voice
            fallback = self.config.voice_en if voice == self.config.voice_hi else self.config.voice_hi
            try:
                async def _retry():
                    comm = edge_tts.Communicate(clean, fallback, rate=self.config.tts_rate)
                    await comm.save(temp_path)

                asyncio.run(_retry())

                if not self._tts_stop.is_set() and not self._stop_event.is_set():
                    pygame.mixer.music.load(temp_path)
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy():
                        if self._tts_stop.is_set() or self._stop_event.is_set():
                            pygame.mixer.music.stop()
                            break
                        pygame.time.Clock().tick(20)
            except Exception:
                pass

        finally:
            self._cleanup_tts(temp_path)

    def _cleanup_tts(self, path: str):
        """Clean up temp TTS file and pygame."""
        try:
            if self._pygame_ready:
                try:
                    pygame.mixer.music.stop()
                    pygame.mixer.music.unload()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if os.path.exists(path):
                os.unlink(path)
        except Exception:
            pass

    def _stop_tts(self):
        """Stop current TTS playback immediately."""
        self._tts_stop.set()
        try:
            if self._pygame_ready and pygame.mixer.get_init():
                try:
                    pygame.mixer.music.stop()
                    pygame.mixer.music.unload()
                except Exception:
                    pass
        except Exception:
            pass

    def _clean_text(self, text: str) -> str:
        """Remove formatting not suitable for speech."""
        import re
        text = re.sub(r"```.*?```", " I displayed the code on screen. ", text, flags=re.DOTALL)
        text = re.sub(r"https?://\S+", " link ", text)
        return text.replace("`", "").replace("*", "").replace("#", "").replace("_", " ").strip()

    # ------------------------------------------------------------------
    # STT
    # ------------------------------------------------------------------

    def _transcribe(self, audio: np.ndarray) -> Optional[str]:
        """Transcribe audio using Google Speech Recognition."""
        try:
            import speech_recognition as sr

            # Convert numpy array to AudioData
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.config.sample_rate)
                wf.writeframes(audio.tobytes())
            wav_bytes = buf.getvalue()

            audiodata = sr.AudioData(wav_bytes, self.config.sample_rate, 2)
            recognizer = sr.Recognizer()
            text = recognizer.recognize_google(audiodata)
            return text.strip()
        except sr.UnknownValueError:
            return None
        except sr.RequestError as e:
            logger.error(f"STT request error: {e}")
            return None
        except Exception as e:
            logger.error(f"STT error: {e}")
            return None

    # ------------------------------------------------------------------
    # Conversation Exit
    # ------------------------------------------------------------------

    def _exit_conversation(self):
        """Exit conversation mode back to IDLE."""
        self._is_conversation = False
        self.state = AssistantState.IDLE
        self._capture_buffer.clear()
        self._in_speech = False
        self._speech_frames = 0
        self._silence_frames = 0
        logger.info("Exited conversation mode")

    def force_exit_conversation(self):
        """Forcefully exit conversation mode (called externally)."""
        self._exit_conversation()

    # ------------------------------------------------------------------
    # Process Loop (background audio processing)
    # ------------------------------------------------------------------

    def _process_loop(self):
        """Background loop that processes buffered audio."""
        while not self._stop_event.is_set():
            # Conversation timeout check
            if self._is_conversation and self.state not in (
                AssistantState.SPEAKING, AssistantState.PROCESSING, AssistantState.CAPTURING
            ):
                if time.time() - self._last_speech_time > self.config.conversation_timeout_seconds:
                    logger.info("Conversation timeout (process loop)")
                    self._exit_conversation()

            self._flush_audio_buffer()
            time.sleep(0.02)  # 20ms polling

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def __del__(self):
        self.stop()

