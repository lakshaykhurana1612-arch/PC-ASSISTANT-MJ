"""
Speech-to-Text — Google Speech Recognition backend.

Provides:
- GoogleSTT: Wraps Google Speech Recognition for reliable one-shot transcription
- No external API keys needed (uses free Google SR)
- Handles numpy arrays, bytes, and AudioData inputs

Backend-agnostic interface for future swapping with Whisper, Deepgram, etc.
"""

from __future__ import annotations

import io
import os
import wave
import logging
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class STTConfig:
    """STT backend configuration."""

    energy_threshold: int = 300
    sample_rate: int = 16000


# ---------------------------------------------------------------------------
# Google STT
# ---------------------------------------------------------------------------


class GoogleSTT:
    """STT using Google Speech Recognition.

    Wraps speech_recognition.recognize_google() with numpy array support.
    No API key required — uses Google's free recognition service.

    Usage:
        stt = GoogleSTT()
        text = stt.transcribe(audio_numpy_array)
    """

    def __init__(self, config: Optional[STTConfig] = None):
        self.config = config or STTConfig()
        self._recognizer = None

    @property
    def is_available(self) -> bool:
        return True  # Always available (internet required)

    def _get_recognizer(self):
        if self._recognizer is None:
            import speech_recognition as sr

            self._recognizer = sr.Recognizer()
            self._recognizer.energy_threshold = self.config.energy_threshold
        return self._recognizer

    def transcribe(self, audio, sample_rate: int = 16000) -> Optional[str]:
        """Transcribe audio using Google Speech Recognition.

        Args:
            audio: numpy int16 array, bytes (WAV), or AudioData.
            sample_rate: sample rate (used for numpy arrays).

        Returns:
            transcribed text string, or None on failure.
        """
        import speech_recognition as sr

        recognizer = self._get_recognizer()

        # Convert various input types to AudioData
        if isinstance(audio, np.ndarray):
            audio_data = self._numpy_to_audiodata(audio, sample_rate)
        elif isinstance(audio, bytes):
            audio_data = sr.AudioData(audio, sample_rate, 2)
        elif isinstance(audio, sr.AudioData):
            audio_data = audio
        else:
            logger.error(f"Unsupported audio type: {type(audio)}")
            return None

        try:
            text = recognizer.recognize_google(audio_data)
            return text.strip()
        except sr.UnknownValueError:
            logger.warning("Google STT could not understand audio.")
            return None
        except sr.RequestError as e:
            logger.error(f"Google STT request error: {e}")
            return None
        except Exception as e:
            logger.error(f"Google STT error: {e}")
            return None

    def _numpy_to_audiodata(self, audio: np.ndarray, sample_rate: int):
        """Convert numpy int16 array to speech_recognition AudioData."""
        import speech_recognition as sr

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(audio.tobytes())
        wav_bytes = buf.getvalue()
        return sr.AudioData(wav_bytes, sample_rate, 2)

    def transcribe_file(self, file_path: str) -> Optional[str]:
        """Transcribe a WAV file directly.

        Args:
            file_path: path to a .wav file.

        Returns:
            transcribed text or None.
        """
        import speech_recognition as sr

        recognizer = self._get_recognizer()
        try:
            with sr.AudioFile(file_path) as source:
                audio = recognizer.record(source)
            text = recognizer.recognize_google(audio)
            return text.strip()
        except Exception as e:
            logger.error(f"File transcription error: {e}")
            return None


# ---------------------------------------------------------------------------
# AutoSTT — simple wrapper (single backend for now)
# ---------------------------------------------------------------------------


class AutoSTT:
    """Automatic STT backend.

    Currently uses Google STT as the sole backend.
    Designed so a future Whisper/Deepgram backend can be swapped in.

    Usage:
        stt = AutoSTT()
        text = stt.transcribe(audio_array)
    """

    def __init__(self, config: Optional[STTConfig] = None):
        self.config = config or STTConfig()
        self._google = GoogleSTT(self.config)

    def transcribe(self, audio, sample_rate: int = 16000) -> Optional[str]:
        """Transcribe audio using Google STT.

        Args:
            audio: numpy int16 array.
            sample_rate: audio sample rate.

        Returns:
            transcribed text or None.
        """
        return self._google.transcribe(audio, sample_rate)

    def transcribe_file(self, file_path: str) -> Optional[str]:
        """Transcribe a WAV file directly."""
        return self._google.transcribe_file(file_path)

