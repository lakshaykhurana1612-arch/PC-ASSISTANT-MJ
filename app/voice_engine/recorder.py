"""
Streaming Audio Recorder — sounddevice backend.

Records PCM audio from microphone in real-time.
Supports:
- Fixed-duration recording (compatibility with old listen())
- Speech-activated recording (VAD-based start/stop)
- Streaming callback for live audio processing
- Configurable sample rate, channels, device

Backend-agnostic: sounddevice can be swapped for PyAudio, etc.
"""

from __future__ import annotations

import io
import os
import time
import wave
import logging
import threading
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class RecorderConfig:
    """Configuration for streaming recorder."""

    sample_rate: int = 16000
    channels: int = 1
    dtype: str = "int16"  # sounddevice dtype
    blocksize: int = 512  # frames per callback
    device: Optional[int] = None  # None = default input device
    silence_timeout_ms: int = 800  # ms of silence before stopping
    max_record_seconds: int = 30  # max recording duration
    min_record_seconds: float = 0.5  # minimum recording to accept


# ---------------------------------------------------------------------------
# Audio Chunk
# ---------------------------------------------------------------------------


@dataclass
class AudioChunk:
    """Represents a chunk of audio data."""

    data: np.ndarray  # numpy array of PCM samples
    sample_rate: int
    timestamp: float  # time.time() when captured
    is_final: bool = False  # True if this is the last chunk


# ---------------------------------------------------------------------------
# StreamingRecorder
# ---------------------------------------------------------------------------


class StreamingRecorder:
    """Real-time audio recorder with VAD integration.

    Usage:
        recorder = StreamingRecorder()

        # Fixed-duration recording (compatible with old listen())
        audio = recorder.record_fixed(duration=6.0)

        # Speech-activated recording
        audio = recorder.record_until_silence(vad_detector, max_duration=30)

        # Streaming with callback
        recorder.start_streaming(on_chunk=my_callback)
        ...
        recorder.stop_streaming()
    """

    def __init__(self, config: Optional[RecorderConfig] = None):
        self.config = config or RecorderConfig()
        self._stream = None  # Will hold sounddevice.Stream
        self._callback_fn: Optional[Callable] = None
        self._is_recording = False
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def sample_rate(self) -> int:
        return self.config.sample_rate

    @property
    def channels(self) -> int:
        return self.config.channels

    @property
    def is_streaming(self) -> bool:
        return self._stream is not None and self._stream.active

    # ------------------------------------------------------------------
    # Fixed-duration recording (backward compatible)
    # ------------------------------------------------------------------

    def record_fixed(self, duration: float = 6.0) -> Optional[np.ndarray]:
        """Record for a fixed duration and return audio array.

        Args:
            duration: recording duration in seconds.

        Returns:
            numpy array of PCM16 int16, or None on failure.
        """
        import sounddevice as sd

        try:
            logger.info(f"Recording for {duration}s...")
            recording = sd.rec(
                int(duration * self.config.sample_rate),
                samplerate=self.config.sample_rate,
                channels=self.config.channels,
                dtype=self.config.dtype,
                device=self.config.device,
            )
            sd.wait()
            return recording.flatten()
        except Exception as e:
            logger.error(f"Record failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Speech-activated recording (VAD-based)
    # ------------------------------------------------------------------

    def record_until_silence(
        self,
        vad,
        max_duration: float = 30.0,
        silence_timeout_ms: Optional[int] = None,
    ) -> Optional[np.ndarray]:
        """Record starting when speech detected, stopping after silence.

        Args:
            vad: VoiceActivityDetector instance.
            max_duration: maximum recording duration in seconds.
            silence_timeout_ms: silence ms before stopping (overrides config).

        Returns:
            numpy array of PCM16 int16, or None on failure.
        """
        import sounddevice as sd

        timeout = silence_timeout_ms or self.config.silence_timeout_ms
        max_samples = int(max_duration * self.config.sample_rate)
        silence_samples = int((timeout / 1000.0) * self.config.sample_rate)
        min_samples = int(self.config.min_record_seconds * self.config.sample_rate)

        buffer: list[np.ndarray] = []
        total_samples = 0
        silent_samples = 0
        speech_detected = False
        started_at = time.time()

        def callback(indata, frames, time_info, status):
            nonlocal total_samples, silent_samples, speech_detected

            if status:
                logger.warning(f"Stream status: {status}")

            chunk = indata.copy().flatten()
            buffer.append(chunk)
            total_samples += len(chunk)

            # VAD check on this chunk
            chunk_speech = vad.is_speech(chunk)
            if chunk_speech:
                speech_detected = True
                silent_samples = 0
            else:
                silent_samples += len(chunk)

        logger.info("Listening for speech (VAD-based)...")

        try:
            with sd.InputStream(
                samplerate=self.config.sample_rate,
                channels=self.config.channels,
                dtype=self.config.dtype,
                blocksize=self.config.blocksize,
                device=self.config.device,
                callback=callback,
            ):
                # Wait for speech or timeout
                wait_start = time.time()
                while not speech_detected and (time.time() - wait_start) < 10:
                    time.sleep(0.05)

                if not speech_detected:
                    logger.info("No speech detected within timeout.")
                    return None

                logger.info("Speech started. Recording...")

                # Now record until silence or max duration
                while total_samples < max_samples:
                    if silent_samples > silence_samples:
                        logger.info("Silence detected. Stopping.")
                        break
                    if (time.time() - started_at) > max_duration:
                        logger.info("Max duration reached. Stopping.")
                        break
                    time.sleep(0.05)

            # Combine all chunks
            if not buffer:
                return None

            full_audio = np.concatenate(buffer)

            # Check minimum length
            if len(full_audio) < min_samples:
                logger.info("Recording too short. Discarding.")
                return None

            logger.info(
                f"Recorded {len(full_audio) / self.config.sample_rate:.1f}s of audio."
            )
            return full_audio

        except Exception as e:
            logger.error(f"Stream recording failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Streaming with callback (for live audio processing)
    # ------------------------------------------------------------------

    def start_streaming(self, on_chunk: Callable[[AudioChunk], None]) -> bool:
        """Start a streaming audio input with callback per chunk.

        Args:
            on_chunk: callback receiving AudioChunk objects.

        Returns:
            True if stream started, False on failure.
        """
        import sounddevice as sd

        if self.is_streaming:
            logger.warning("Stream already active.")
            return False

        self._callback_fn = on_chunk
        self._stop_event.clear()

        def callback(indata, frames, time_info, status):
            if status:
                logger.warning(f"Stream status: {status}")
            if self._stop_event.is_set():
                raise sd.CallbackStop()

            chunk = AudioChunk(
                data=indata.copy().flatten(),
                sample_rate=self.config.sample_rate,
                timestamp=time.time(),
            )
            try:
                if self._callback_fn:
                    self._callback_fn(chunk)
            except Exception as e:
                logger.error(f"Chunk callback error: {e}")

        try:
            self._stream = sd.InputStream(
                samplerate=self.config.sample_rate,
                channels=self.config.channels,
                dtype=self.config.dtype,
                blocksize=self.config.blocksize,
                device=self.config.device,
                callback=callback,
            )
            self._stream.start()
            logger.info("Streaming started.")
            return True
        except Exception as e:
            logger.error(f"Failed to start streaming: {e}")
            return False

    def stop_streaming(self) -> None:
        """Stop the streaming input."""
        self._stop_event.set()
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.error(f"Error stopping stream: {e}")
            self._stream = None
        self._callback_fn = None
        logger.info("Streaming stopped.")

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def audio_to_bytes(self, audio: np.ndarray) -> bytes:
        """Convert numpy int16 array to raw PCM bytes."""
        return audio.tobytes()

    def audio_to_wav_bytes(self, audio: np.ndarray) -> bytes:
        """Convert numpy int16 array to WAV bytes."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.config.channels)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.config.sample_rate)
            wf.writeframes(audio.tobytes())
        return buf.getvalue()

    def __del__(self):
        self.stop_streaming()

