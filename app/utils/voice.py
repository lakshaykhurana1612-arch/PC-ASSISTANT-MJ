"""Text-to-speech and microphone input utilities for MJ."""

import asyncio
import os
import re
import tempfile
import time
import traceback
from pathlib import Path

import edge_tts
import speech_recognition as sr


os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame

VOICE_NAME = "en-IN-NeerjaNeural"
VOICE_FALLBACK = "hi-IN-SwaraNeural"  # Hindi voice for Hindi/Hinglish text
VOICE_RATE = "+25%"
CAPTURE_SECONDS = 6
DEBUG_AUDIO_PATH = Path("debug.wav")

def _get_temp_tts_path() -> Path:
    """Generate a unique temp file path for TTS audio to avoid PermissionError collisions."""
    fd, path = tempfile.mkstemp(suffix=".mp3", prefix="mj_voice_")
    os.close(fd)  # Close the file descriptor immediately; we only need the path
    return Path(path)


def _safe_unlink(path: Path, max_retries: int = 3) -> None:
    """Delete a file with retry logic to handle Windows file-lock delays."""
    for attempt in range(max_retries):
        try:
            if path.exists():
                path.unlink()
            return
        except PermissionError:
            if attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))
            else:
                # Log but don't crash — Windows may still hold the handle
                print(f"[VOICE] Warning: could not delete {path.name} after {max_retries} retries")
        except Exception:
            return


def _handle_tts_fallback(spoken_text: str, primary_voice: str) -> Path | None:
    """Try TTS with the alternative voice on a unique temp path.

    Returns the fallback file path if successful, None otherwise.
    """
    fallback_voice = VOICE_NAME if primary_voice == VOICE_FALLBACK else VOICE_FALLBACK
    fallback_path = _get_temp_tts_path()
    try:
        async def _retry() -> None:
            comm = edge_tts.Communicate(spoken_text, fallback_voice, rate=VOICE_RATE)
            await comm.save(str(fallback_path))
        asyncio.run(_retry())
        if fallback_path.exists():
            _release_pygame_audio()
            pygame.mixer.music.load(str(fallback_path))
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(20)
            return fallback_path
    except Exception:
        _safe_unlink(fallback_path)
    return None


def _release_pygame_audio() -> None:
    """Safely stop and unload any pygame audio to release file handles."""
    if not _AUDIO_OUTPUT_READY:
        return
    try:
        if pygame.mixer.get_init():
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
            try:
                pygame.mixer.music.unload()
            except Exception:
                pass
    except Exception:
        pass

# Set MJ_MICROPHONE_INDEX only when you need a specific Windows input device.
# Leaving it unset follows the microphone selected in Windows Sound settings.
_configured_device = os.getenv("MJ_MICROPHONE_INDEX")
MICROPHONE_DEVICE_INDEX = int(_configured_device) if _configured_device else None

try:
    pygame.mixer.init()
    _AUDIO_OUTPUT_READY = True
except pygame.error as error:
    _AUDIO_OUTPUT_READY = False
    print(f"[VOICE] Speaker initialization failed: {error}")


def _has_hindi(text: str) -> bool:
    """Check if text contains Devanagari (Hindi) characters."""
    return bool(re.search(r"[\u0900-\u097F]", text))


def _clean_for_speech(text: str) -> str:
    """Remove formatting that should not be spoken aloud."""
    text = re.sub(r"```.*?```", " I displayed the code on screen. ", text, flags=re.DOTALL)
    text = re.sub(r"https?://\S+", " link ", text)
    return text.replace("`", "").replace("*", "").replace("#", "").replace("_", " ").strip()


def speak(text: str) -> None:
    """Speak text through Edge TTS and clean up the temporary audio file."""
    print(f"\nMJ: {text}\n")

    # Duplex hook: notify listener that TTS started.
    # (We mark only start; listener uses a time gate.)
    try:
        from app.utils.duplex_state import get_global_duplex_voice

        dv = get_global_duplex_voice()
        if dv is not None:
            dv.mark_tts_started()
    except Exception:
        pass

    spoken_text = _clean_for_speech(text)
    if not spoken_text:
        # Nothing to speak => mark finished so duplex gating ends.
        try:
            from app.utils.duplex_state import get_global_duplex_voice

            dv = get_global_duplex_voice()
            if dv is not None:
                dv.mark_tts_finished()
        except Exception:
            pass
        return

    if not _AUDIO_OUTPUT_READY:
        print("[VOICE] Cannot speak because the audio output is unavailable.")
        return

    # Pick the right voice: Hindi voice for Hindi text, English voice otherwise
    voice = VOICE_FALLBACK if _has_hindi(spoken_text) else VOICE_NAME

    tts_path = _get_temp_tts_path()
    fallback_path = None

    try:
        _release_pygame_audio()

        async def generate_audio() -> None:
            communicator = edge_tts.Communicate(spoken_text, voice, rate=VOICE_RATE)
            await communicator.save(str(tts_path))

        asyncio.run(generate_audio())

        if not tts_path.exists():
            raise FileNotFoundError(f"TTS output not created: {tts_path}")

        pygame.mixer.music.load(str(tts_path))
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(20)

    except PermissionError as error:
        print(f"[VOICE] PermissionError (file lock): {error}")
        fb = _handle_tts_fallback(spoken_text, voice)
        if fb:
            fallback_path = fb
    except Exception as error:
        print(f"[VOICE] TTS failed: {type(error).__name__}: {error}")
        fb = _handle_tts_fallback(spoken_text, voice)
        if fb:
            fallback_path = fb
    finally:
        _release_pygame_audio()
        _safe_unlink(tts_path)
        if fallback_path:
            _safe_unlink(fallback_path)

        try:
            from app.utils.duplex_state import get_global_duplex_voice
            dv = get_global_duplex_voice()
            if dv is not None:
                dv.mark_tts_finished()
        except Exception:
            pass



def _microphone_label() -> str:
    """Return the selected input's name when PyAudio can enumerate devices."""
    if MICROPHONE_DEVICE_INDEX is None:
        return "Windows default"

    try:
        return sr.Microphone.list_microphone_names()[MICROPHONE_DEVICE_INDEX]
    except (AttributeError, IndexError, OSError):
        return str(MICROPHONE_DEVICE_INDEX)


def listen() -> str | None:
    """Record one command and return its Google Speech Recognition transcript."""
    recognizer = sr.Recognizer()
    microphone = sr.Microphone(device_index=MICROPHONE_DEVICE_INDEX)

    try:
        with microphone as source:
            device_label = _microphone_label()
            print(f"\n[VOICE] Listening on microphone: {device_label}")
            print(f"[VOICE] Speak now. Recording for {CAPTURE_SECONDS} seconds...")
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio = recognizer.record(source, duration=CAPTURE_SECONDS)

        DEBUG_AUDIO_PATH.write_bytes(audio.get_wav_data())
        print(f"[VOICE] Audio saved to {DEBUG_AUDIO_PATH} ({DEBUG_AUDIO_PATH.stat().st_size} bytes).")
        print("[VOICE] Transcribing with Google Speech Recognition...")
        text = recognizer.recognize_google(audio).strip()
        print(f"[VOICE] Heard: {text}")
        return text

    except sr.UnknownValueError:
        print("[VOICE] Google could not understand the audio.")
    except sr.RequestError as error:
        print(f"[VOICE] Google Speech Recognition error: {error}")
    except OSError as error:
        print(f"[VOICE] Microphone error: {error}")
    except Exception as error:
        print(f"[VOICE] Unexpected listener error: {type(error).__name__}: {error}")
        traceback.print_exc()

    return None


def listen_wake():
    """Listen for a short phrase and return its Google transcript."""
    recognizer = sr.Recognizer()
    microphone = sr.Microphone(device_index=MICROPHONE_DEVICE_INDEX)

    with microphone as source:
        try:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio = recognizer.listen(source, timeout=4, phrase_time_limit=2)
            text = recognizer.recognize_google(audio).strip()
            return text.lower()

        except sr.WaitTimeoutError:
            return None
        except sr.UnknownValueError:
            return None
        except sr.RequestError:
            return None
        except Exception:
            return None

