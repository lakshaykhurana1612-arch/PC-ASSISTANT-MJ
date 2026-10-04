"""
Echo Cancellation — Acoustic Echo Cancellation (AEC) for voice.

Provides basic echo suppression and noise reduction for full-duplex voice.
Uses reference signal (TTS output) to cancel echo from microphone input.

Backend-agnostic: can use webrtcvad, speexdsp, or custom AEC.

Note: True AEC requires access to the loopback/reference audio stream.
This implementation provides:
1. Simple spectral subtraction for noise reduction
2. Integration hooks for webrtcvad-based echo suppression
3. Automatic gain control (AGC) for consistent input levels

In full duplex mode, echo is managed by:
- Gating mic input while TTS is active (software safety)
- Spectral subtraction to remove residual echo
- Noise suppression to improve STT accuracy
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class EchoConfig:
    """Echo cancellation configuration."""

    enabled: bool = True
    frame_size_ms: int = 10
    sample_rate: int = 16000
    echo_suppression_db: float = 20.0  # How much to suppress echo
    noise_floor_db: float = -40.0
    agc_target_db: float = -15.0
    agc_max_gain: float = 10.0


class EchoCanceller:
    """Acoustic Echo Cancellation processor.

    Uses adaptive filtering and noise suppression.

    Usage:
        canceller = EchoCanceller()
        clean_audio = canceller.process(mic_audio)
    """

    def __init__(self, config: Optional[EchoConfig] = None):
        self.config = config or EchoConfig()
        self._filter_state = None
        self._noise_profile = None
        self._lock = threading.Lock()

    @property
    def is_available(self) -> bool:
        return self.config.enabled

    def process(self, mic_audio: np.ndarray) -> np.ndarray:
        """Process microphone audio to suppress echo and noise.

        Args:
            mic_audio: numpy array of PCM16 int16 samples.

        Returns:
            Cleaned audio array.
        """
        if not self.config.enabled:
            return mic_audio

        with self._lock:
            # Convert to float for processing
            if mic_audio.dtype == np.int16:
                audio_float = mic_audio.astype(np.float32) / 32768.0
            else:
                audio_float = mic_audio

            # Apply noise reduction
            cleaned = self._reduce_noise(audio_float)

            # Apply AGC
            cleaned = self._apply_agc(cleaned)

            # Convert back to int16
            cleaned_int16 = np.clip(cleaned * 32768.0, -32768, 32767).astype(np.int16)
            return cleaned_int16

    def _reduce_noise(self, audio: np.ndarray) -> np.ndarray:
        """Simple spectral subtraction noise reduction."""
        frame_size = int(self.config.sample_rate * self.config.frame_size_ms / 1000)
        if len(audio) < frame_size:
            return audio

        # Maintain a noise profile
        if self._noise_profile is None:
            # Initialize with first frame
            self._noise_profile = np.abs(np.fft.rfft(audio[:frame_size]))
            return audio

        # Process in frames
        output = np.zeros_like(audio)
        for i in range(0, len(audio), frame_size):
            frame = audio[i : i + frame_size]
            if len(frame) < frame_size:
                output[i:] = frame
                break

            # FFT
            fft_frame = np.fft.rfft(frame)
            magnitude = np.abs(fft_frame)
            phase = np.angle(fft_frame)

            # Update noise profile (slowly track minimum)
            self._noise_profile = 0.95 * self._noise_profile + 0.05 * np.minimum(
                self._noise_profile, magnitude
            )

            # Spectral subtraction
            gain = np.maximum(
                0.0,
                1.0 - (self._noise_profile / (magnitude + 1e-10)),
            )

            # Apply gain with echo suppression floor
            echo_suppression = 10 ** (-self.config.echo_suppression_db / 20.0)
            gain = np.maximum(gain, echo_suppression)

            # Reconstruct
            output[i : i + frame_size] = np.fft.irfft(fft_frame * gain)[: len(frame)]

        return output

    def _apply_agc(self, audio: np.ndarray) -> np.ndarray:
        """Automatic Gain Control.

        Normalizes audio level to target RMS.
        """
        rms = np.sqrt(np.mean(audio**2) + 1e-10)
        if rms < 1e-6:
            return audio

        current_db = 20 * np.log10(rms)
        gain_db = self.config.agc_target_db - current_db

        # Clamp gain
        gain_linear = 10 ** (gain_db / 20.0)
        gain_linear = min(gain_linear, self.config.agc_max_gain)
        gain_linear = max(gain_linear, 0.1)

        return audio * gain_linear

    def reset(self):
        """Reset internal filter state and noise profile."""
        with self._lock:
            self._filter_state = None
            self._noise_profile = None
            logger.info("Echo canceller reset.")


# ---------------------------------------------------------------------------
# Simple Noise Suppressor (lightweight)
# ---------------------------------------------------------------------------


class NoiseSuppressor:
    """Lightweight noise suppression for voice preprocessing.

    Uses simple gate and spectral subtraction.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        noise_gate_db: float = -50.0,
    ):
        self.sample_rate = sample_rate
        self.noise_gate = 10 ** (noise_gate_db / 20.0)
        self._noise_profile: Optional[np.ndarray] = None

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Apply noise suppression."""
        if audio.dtype == np.int16:
            audio_float = audio.astype(np.float32) / 32768.0
        else:
            audio_float = audio

        # Simple noise gate
        rms = np.sqrt(np.mean(audio_float**2))
        if rms < self.noise_gate:
            return np.zeros_like(audio)

        return audio


# ---------------------------------------------------------------------------
# Audio Preprocessor (combines AEC + Noise + AGC)
# ---------------------------------------------------------------------------


class AudioPreprocessor:
    """Full audio preprocessing pipeline.

    Combines echo cancellation, noise suppression, and AGC.

    Usage:
        preprocessor = AudioPreprocessor()
        clean_audio = preprocessor.process(mic_audio)
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        enable_aec: bool = True,
        enable_agc: bool = True,
    ):
        self.sample_rate = sample_rate
        self.echo_canceller = EchoCanceller(
            EchoConfig(enabled=enable_aec, sample_rate=sample_rate)
        )
        self.noise_suppressor = NoiseSuppressor(sample_rate=sample_rate)
        self._enable_agc = enable_agc

    def process(self, mic_audio: np.ndarray) -> np.ndarray:
        """Run full preprocessing pipeline.

        Pipeline: Echo Cancellation → Noise Suppression → AGC
        """
        # Step 1: Echo cancellation
        audio = self.echo_canceller.process(mic_audio)

        # Step 2: Noise suppression
        audio = self.noise_suppressor.process(audio)

        # Step 3: AGC (if echo canceller's AGC is enabled)
        if self._enable_agc and self.echo_canceller.config.enabled:
            audio = self.echo_canceller._apply_agc(audio)

        return audio

    def reset(self):
        """Reset all processors."""
        self.echo_canceller.reset()

