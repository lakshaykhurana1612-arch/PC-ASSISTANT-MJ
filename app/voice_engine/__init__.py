"""
MJ Voice Engine — Streaming voice pipeline.

Components:
- VoiceAssistant: Unified voice assistant (VAD + STT + TTS + wake word)
- WakeWordDetector: Lightweight wake word detection (VAD + Google STT)
- ConversationManager: Thin wrapper around VoiceAssistant
- VoiceActivityDetector: Silero VAD backend
- StreamingRecorder: sounddevice audio recorder
- GoogleSTT / AutoSTT: Speech-to-text backends
- InterruptibleTTS: Edge TTS with preemption
- StreamingSTT (placeholder for future Deepgram)
- EchoCanceller / AudioPreprocessor: Echo cancellation

All components expose clean interfaces for backend swapping.
"""

from app.voice_engine.voice_assistant import VoiceAssistant, VoiceAssistantConfig, AssistantState
from app.voice_engine.conversation import ConversationManager, ConversationConfig
from app.voice_engine.wake_word import WakeWordDetector, WakeWordConfig
from app.voice_engine.vad import VoiceActivityDetector
from app.voice_engine.recorder import StreamingRecorder, RecorderConfig, AudioChunk
from app.voice_engine.stt import GoogleSTT, AutoSTT, STTConfig
from app.voice_engine.tts import InterruptibleTTS, TTSConfig
from app.voice_engine.echo import EchoCanceller, NoiseSuppressor, AudioPreprocessor, EchoConfig

__all__ = [
    "VoiceAssistant",
    "VoiceAssistantConfig",
    "AssistantState",
    "ConversationManager",
    "ConversationConfig",
    "WakeWordDetector",
    "WakeWordConfig",
    "VoiceActivityDetector",
    "StreamingRecorder",
    "RecorderConfig",
    "AudioChunk",
    "GoogleSTT",
    "AutoSTT",
    "STTConfig",
    "InterruptibleTTS",
    "TTSConfig",
    "EchoCanceller",
    "NoiseSuppressor",
    "AudioPreprocessor",
    "EchoConfig",
]
