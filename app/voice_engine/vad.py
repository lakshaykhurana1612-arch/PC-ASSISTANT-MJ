"""
Voice Activity Detection — Silero VAD backend.

Detects speech in raw PCM audio chunks in real-time.
Exposes a simple `is_speech(audio_chunk) -> bool` interface.

Backend-agnostic: Silero VAD can be swapped for WebRTC VAD or other.
"""

from __future__ import annotations

import os
import sys
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Silero VAD wrapper
# ---------------------------------------------------------------------------

_SILERO_AVAILABLE = False
_get_tensor = None
_get_speech_timestamps = None
_Model = None
_utils_silero = None


def _lazy_load_silero():
    """Import and cache Silero VAD model on first use."""
    global _SILERO_AVAILABLE, _get_tensor, _get_speech_timestamps, _Model, _utils_silero

    if _SILERO_AVAILABLE:
        return

    try:
        import torch
        import torchaudio
        import silero_vad

        # Silero VAD v5+ style
        _Model = silero_vad.load_silero_vad()

        # Helper functions
        def _load_audio(path_or_bytes, sampling_rate=16000):
            if isinstance(path_or_bytes, (str, os.PathLike)):
                waveform, sr = torchaudio.load(path_or_bytes)
            else:
                # Assume bytes
                import io
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    f.write(path_or_bytes)
                    tmp_path = f.name
                try:
                    waveform, sr = torchaudio.load(tmp_path)
                finally:
                    os.unlink(tmp_path)

            if sr != sampling_rate:
                resampler = torchaudio.transforms.Resample(sr, sampling_rate)
                waveform = resampler(waveform)

            return waveform

        _get_tensor = _load_audio

        _SILERO_AVAILABLE = True
        logger.info("Silero VAD loaded successfully.")

    except ImportError:
        logger.warning(
            "Silero VAD not installed. Install with: pip install silero-vad torch torchaudio"
        )
    except Exception as e:
        logger.warning(f"Silero VAD load failed: {e}")


# ---------------------------------------------------------------------------
# VoiceActivityDetector
# ---------------------------------------------------------------------------


class VoiceActivityDetector:
    """Real-time voice activity detection.

    Usage:
        vad = VoiceActivityDetector(sample_rate=16000)
        vad.is_speech(audio_chunk)      # numpy array of PCM16 int16
        vad.is_speech_bytes(raw_bytes)  # raw PCM16 bytes
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        threshold: float = 0.5,
        min_speech_duration_ms: int = 100,
        min_silence_duration_ms: int = 300,
    ):
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.min_speech_duration_ms = min_speech_duration_ms
        self.min_silence_duration_ms = min_silence_duration_ms

        _lazy_load_silero()

        # State for continuous detection
        self._speech_history: list[bool] = []
        self._consecutive_speech = 0
        self._consecutive_silence = 0

    @property
    def is_available(self) -> bool:
        return _SILERO_AVAILABLE

    def is_speech(self, audio_chunk, sample_rate: Optional[int] = None) -> bool:
        """Check if the given audio chunk contains speech.

        Args:
            audio_chunk: numpy array of PCM16 int16 samples.
            sample_rate: sampling rate (defaults to self.sample_rate).

        Returns:
            True if speech detected, False otherwise.
        """
        if not _SILERO_AVAILABLE:
            # Fallback: assume always speech (let downstream handle it)
            return True

        sr = sample_rate or self.sample_rate

        try:
            import torch
            import silero_vad

            # Convert int16 to float32 tensor
            if hasattr(audio_chunk, "dtype") and audio_chunk.dtype in (
                "int16",
                "<i2",
                ">i2",
            ):
                audio_float = audio_chunk.astype("float32") / 32768.0
            else:
                audio_float = audio_chunk

            if isinstance(audio_float, torch.Tensor):
                tensor = audio_float
            else:
                tensor = torch.from_numpy(audio_float).float()

            # Ensure 1D
            if tensor.dim() > 1:
                tensor = tensor.squeeze()

            speech_prob = silero_vad.get_speech_timestamps(
                tensor,
                _Model,
                sampling_rate=sr,
                threshold=self.threshold,
                return_seconds=False,
            )

            # Silero returns list of speech segments; non-empty = speech
            return len(speech_prob) > 0

        except Exception as e:
            logger.error(f"VAD inference error: {e}")
            return True  # Safe fallback

    def is_speech_bytes(self, raw_bytes: bytes, sample_rate: Optional[int] = None) -> bool:
        """Check speech from raw PCM16 bytes."""
        import numpy as np

        audio = np.frombuffer(raw_bytes, dtype=np.int16)
        return self.is_speech(audio, sample_rate)

    def reset_state(self):
        """Reset the internal speech/silence counters."""
        self._speech_history.clear()
        self._consecutive_speech = 0
        self._consecutive_silence = 0

    # ------------------------------------------------------------------
    # Continuous detection helpers (for streaming recorder)
    # ------------------------------------------------------------------

    def update(self, is_speech: bool) -> str | None:
        """Update state with a detection result.

        Args:
            is_speech: whether current frame has speech.

        Returns:
            - "speech_start" if speech just began after silence
            - "speech_end" if silence just began after speech
            - "in_speech" if currently in speech
            - "in_silence" if currently in silence
            - None if state unchanged
        """
        self._speech_history.append(is_speech)

        if is_speech:
            self._consecutive_speech += 1
            self._consecutive_silence = 0
        else:
            self._consecutive_silence += 1
            self._consecutive_speech = 0

        # Speech start detection
        if (
            is_speech
            and self._consecutive_speech == 1
            and self._consecutive_silence == 0
        ):
            return "speech_start"

        # Speech end detection (silence for X ms)
        silence_frames_for_end = int(
            self.min_silence_duration_ms / (1000 / self.sample_rate * 512)
        )
        if (
            not is_speech
            and self._consecutive_silence >= max(1, silence_frames_for_end)
            and any(self._speech_history[-10:])
        ):
            return "speech_end"

        if is_speech:
            return "in_speech"
        return "in_silence"

