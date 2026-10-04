"""MJ Assistant — Main Entry Point.

Voice System (rewritten):
- VoiceAssistant: Always-on VAD listening, like ChatGPT/Gemini voice
- WakeWordDetector: Lightweight VAD + keyword wake word
- Continuous conversation mode with natural interrupt

Brain pipeline:
- Smart mode: Intent Router -> Planner -> LLM -> Validator -> Executor
- Classic mode: Legacy analyze_command_with_ai() flow (DEFAULT)
"""

import sys
import os
import time
import logging
import subprocess

import google.genai as genai
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Path & Environment Setup
# ---------------------------------------------------------------------------

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

load_dotenv()

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("MJ")

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from app.utils.file_manager import find_file, open_file
from app.utils.whatsapp import send_resume_via_whatsapp
from app.utils.error_manager import report_error_to_mj
from app.brain.groq_client import analyze_command_with_ai
from app.utils.voice import speak, listen, listen_wake
from app.utils.actions import execute_smart_action
from app.utils import error_manager
import keyboard

error_manager.LAST_COMMAND = error_manager.save_error(module=__file__)


# ===========================================================================
# BRAIN MODE — Smart Pipeline (opt-in)
# ===========================================================================

_SMART_MODE = False
_SMART_ORCHESTRATOR = None


def _get_smart_orchestrator():
    global _SMART_ORCHESTRATOR
    if _SMART_ORCHESTRATOR is None:
        from app.planner.planner import PipelineOrchestrator
        _SMART_ORCHESTRATOR = PipelineOrchestrator()
    return _SMART_ORCHESTRATOR


def _voice_assistant_speak(text: str):
    """Speak using VoiceAssistant if active, otherwise fallback to legacy speak().

    This is critical: when VoiceAssistant is in conversation mode, ALL TTS must go
    through va.speak() so the state machine transitions to SPEAKING and blocks mic
    input during TTS playback. Otherwise TTS echo from speakers would be picked up
    by the mic, transcribed as a false command, and potentially exit the conversation.
    """
    if _VOICE_ASSISTANT is not None and _VOICE_ASSISTANT.in_conversation:
        _VOICE_ASSISTANT.speak(text)
    else:
        speak(text)


def _process_smart_pipeline(user_input: str) -> None:
    if not user_input:
        return
    orchestrator = _get_smart_orchestrator()
    response = orchestrator.process(
        user_input=user_input,
        mode="classic",
        execute_plan=True,
    )
    if response and response.speech_text:
        _voice_assistant_speak(response.speech_text)
    elif response and response.display_text:
        print(f"\nMJ: {response.display_text}")
    else:
        _voice_assistant_speak("Boss, kuch response nahi mila.")


# ===========================================================================
# VOICE ASSISTANT — Unified Voice Engine (NEW)
# ===========================================================================
# Uses VoiceAssistant from voice_engine for:
# - Always-on VAD listening (like ChatGPT/Gemini)
# - Wake word activation ("mj")
# - Continuous conversation mode
# - Natural interrupt (speak over TTS)

_VOICE_ASSISTANT = None
_LAST_COMMAND_TEXT = ""
_LAST_COMMAND_TIME = 0.0

def _get_voice_assistant():
    """Get or create the VoiceAssistant instance."""
    global _VOICE_ASSISTANT
    if _VOICE_ASSISTANT is None:
        from app.voice_engine.voice_assistant import VoiceAssistant, VoiceAssistantConfig

        config = VoiceAssistantConfig(
            wake_word="mj",
            vad_mode=1,
            min_silence_duration_ms=600,
            max_record_seconds=10.0,
            conversation_timeout_seconds=15.0,
        )
        _VOICE_ASSISTANT = VoiceAssistant(
            on_command=_on_voice_command,
            on_wake=_on_wake_detected,
            config=config,
        )
    return _VOICE_ASSISTANT


def _on_wake_detected():
    """Called when wake word is detected."""
    logger.info("Wake word detected!")
    # Wake response is handled by VoiceAssistant internally


def _on_voice_command(text: str):
    """Callback when VoiceAssistant produces a command."""
    if not text:
        return
    print(f"\n\u2705 Voice command: {text}")
    _process_ai_pipeline(text)


# ===========================================================================
# AI PIPELINE — Unified handler
# ===========================================================================

def _process_ai_pipeline(user_input: str) -> None:
    """Run the AI pipeline: LLM -> Action Executor -> Response."""
    global _LAST_COMMAND_TEXT, _LAST_COMMAND_TIME

    if not user_input:
        return

    # Dedup check: skip if same text was processed within last 1.5 seconds
    normalized = user_input.strip().lower()
    now = time.time()
    if normalized == _LAST_COMMAND_TEXT and (now - _LAST_COMMAND_TIME) < 1.5:
        logger.warning(f"Dedup: blocked duplicate processing of '{user_input}'")
        return

    _LAST_COMMAND_TEXT = normalized
    _LAST_COMMAND_TIME = now

    # System commands
    if _handle_system_command(user_input):
        return

    # SMART MODE
    if _SMART_MODE:
        _process_smart_pipeline(user_input)
        return

    # CLASSIC MODE (DEFAULT)
    print("\n[MJ is thinking...]")
    ai_decision = analyze_command_with_ai(user_input)

    if not ai_decision:
        _voice_assistant_speak("Server se response nahi mila yaar.")
        return

    print(f"[AI Decision] {ai_decision[:200]}...")

    if "FILE_SEARCH:" in ai_decision:
        result = execute_smart_action(ai_decision)
        if result:
            _voice_assistant_speak(result)
        return

    if "SEARCH:" in ai_decision:
        print("[MJ is searching the web...]")
        search_result = execute_smart_action(ai_decision)
        final_prompt = f"""
User asked:
{user_input}

Internet Search Results:
{search_result}

Answer naturally in 2-4 sentences.
"""
        final_answer = analyze_command_with_ai(final_prompt)
        if final_answer:
            execute_smart_action(final_answer)
            if "CHAT:" in final_answer:
                chat_text = final_answer.split("CHAT:")[1].split("&&")[0].strip()
                _voice_assistant_speak(chat_text)
        return

    result = execute_smart_action(ai_decision)
    if result:
        _voice_assistant_speak(result)
    elif "CHAT:" in ai_decision:
        chat_text = ai_decision.split("CHAT:")[1].split("&&")[0].strip()
        _voice_assistant_speak(chat_text)


# ===========================================================================
# SYSTEM COMMANDS
# ===========================================================================

def _handle_system_command(text: str) -> bool:
    """Handle system commands. Returns True if handled."""
    global _SMART_MODE
    t = text.strip().lower()

    # Brain mode switching
    if t in ("use smart mode", "smart mode", "enable smart mode", "switch to smart"):
        _SMART_MODE = True
        speak("Smart mode activated Boss! Intent router se processing kar rahi hoon.")
        return True

    if t in ("use classic brain", "classic brain", "disable smart mode", "switch to classic brain"):
        _SMART_MODE = False
        speak("Classic brain mode activated Boss. Purane tareeke se kaam kar rahi hoon.")
        return True

    if t in ("toggle smart mode", "toggle brain mode"):
        _SMART_MODE = not _SMART_MODE
        mode_name = "smart" if _SMART_MODE else "classic brain"
        speak(f"{mode_name.capitalize()} mode activated Boss.")
        return True

    # Voice assistant control
    if t in ("start voice", "voice on", "enable voice", "start conversation"):
        va = _get_voice_assistant()
        if va.start_conversation():
            va.speak("Voice assistant activated Boss. Directly sun rahi hoon, wake word ki zaroorat nahi hai.")
        else:
            va.speak("Boss, voice assistant start nahi ho paaya. VAD check karo.")
        return True

    if t in ("stop voice", "voice off", "disable voice", "stop conversation"):
        va = _get_voice_assistant()
        va.stop()
        speak("Voice assistant deactivated.")
        return True

    if t in ("start duplex", "open duplex", "enable duplex", "duplex on", "conversation mode"):
        va = _get_voice_assistant()
        if va.start_conversation():
            va.speak("Duplex mode ON. Continuous voice sun rahi hoon Boss.")
        else:
            va.speak("Boss, duplex mode start nahi ho paaya.")
        return True

    if t in ("stop duplex", "close duplex", "disable duplex", "duplex off"):
        va = _get_voice_assistant()
        va.force_exit_conversation()
        va.stop()
        speak("Duplex mode OFF.")
        return True

    if t in ("start wake", "enable wake word", "wake on", "mj wake"):
        _start_wake_word()
        speak("Wake word active. Just say MJ.")
        return True

    if t in ("stop wake", "disable wake word", "wake off"):
        _stop_wake_word()
        speak("Wake word disabled.")
        return True

    return False


# ===========================================================================
# WAKE WORD (Lightweight — uses WakeWordDetector)
# ===========================================================================

_WAKE_DETECTOR = None

def _start_wake_word():
    """Start wake word detection in background."""
    global _WAKE_DETECTOR
    if _WAKE_DETECTOR is not None and _WAKE_DETECTOR.is_running:
        return

    from app.voice_engine.wake_word import WakeWordDetector

    def on_wake():
        speak("Ji Boss!")

    def on_command(cmd: str):
        if cmd:
            _process_ai_pipeline(cmd)

    _WAKE_DETECTOR = WakeWordDetector(
        on_wake=on_wake,
        on_transcript=on_command,
    )
    _WAKE_DETECTOR.start()


def _stop_wake_word():
    """Stop wake word detection."""
    global _WAKE_DETECTOR
    if _WAKE_DETECTOR:
        _WAKE_DETECTOR.stop()
        _WAKE_DETECTOR = None


# ===========================================================================
# GEMINI FALLBACK
# ===========================================================================

def get_response_with_fallback(prompt):
    key1 = os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY_1")
    key2 = os.getenv("GEMINI_API_KEY_2")

    try:
        genai.configure(api_key=key1)
        model = genai.GenerativeModel("gemini-2.5-flash")
        return model.generate_content(prompt).text
    except Exception as e:
        print(f"Primary failed, switching to backup... ({e})")
        try:
            genai.configure(api_key=key2)
            model = genai.GenerativeModel("gemini-2.5-flash")
            return model.generate_content(prompt).text
        except Exception as e2:
            return "MJ Error: Backup API bhi kaam nahi kar rahi."


# ===========================================================================
# RUN MJ (hotkey / wake-word entry point)
# ===========================================================================

def run_mj(user_input=None):
    """Entry point for hotkey activation."""
    if user_input is None:
        speak("Ji Boss!")
        user_input = listen()

    if not user_input:
        return

    print(f"\u2705 You said: {user_input}")

    # Direct file search shortcut
    if any(word in user_input.lower() for word in ["open", "search"]):
        clean_q = (
            user_input.lower()
            .replace("open", "")
            .replace("search", "")
            .replace("file", "")
            .replace("pdf", "")
            .strip()
        )
        print(f"DEBUG: Searching for: {clean_q}")
        path = find_file(clean_q)
        if path:
            open_file(path)
            speak("Boss, file mil gayi.")
        else:
            speak(f"Boss, '{clean_q}' naam ki file nahi mili.")
        return

    _process_ai_pipeline(user_input)


# ===========================================================================
# MAIN LOOP
# ===========================================================================

def main():
    """Main interactive loop with keyboard + voice support."""
    speak("Hello Boss! MJ ready hai.")

    while True:
        print("\n" + "=" * 55)
        print("TYPE command | Just Enter for VOICE | 'exit' to quit")
        print("Type 'start duplex' for continuous voice mode")
        print("=" * 55)

        try:
            user_input = input("You: ").strip()

            # Voice mode
            if user_input == "":
                user_input = listen()
                if not user_input:
                    print("\nMJ could not transcribe. Check VOICE TRACE above.")
                    continue

            # Exit
            if user_input.lower() in ["exit", "bye"]:
                speak("Bye bye Boss! Apna khayal rakhna.")
                break

            # System commands
            if _handle_system_command(user_input):
                continue

            print("\n[MJ is thinking...]")
            _process_ai_pipeline(user_input)

        except KeyboardInterrupt:
            speak("Bye bye Boss!")
            break
        except Exception as e:
            error_manager.save_error(
                command=user_input if 'user_input' in locals() else '',
                module=__file__
            )
            import traceback
            traceback.print_exc()


# ===========================================================================
# PROCESS COMMAND (legacy helper)
# ===========================================================================

def process_command(command):
    """Legacy process_command for WhatsApp + file search."""
    ai_decision = analyze_command_with_ai(command)
    commands = ai_decision.split("&&")

    found_path = None
    for cmd in commands:
        cmd = cmd.strip()

        if cmd.startswith("FILE_SEARCH:"):
            query = cmd.split("FILE_SEARCH:")[1].strip()
            found_path = find_file(query)

        elif cmd.startswith("WHATSAPP_MSG:"):
            parts = cmd.split("WHATSAPP_MSG:")[1].split("|")
            contact = parts[0].strip()
            if found_path:
                print(f"Executing WhatsApp Send for: {contact}")
                send_resume_via_whatsapp(contact, found_path)


# ===========================================================================
# MJ AVATAR LAUNCHER
# ===========================================================================

def _launch_godot_avatar():
    """Launch the MJ Godot avatar scene from Godot editor/runtime."""
    godot_exe = r"D:\Godot_v4.7.1-stable_win64.exe\Godot_v4.7.1-stable_win64.exe"
    project_path = os.path.join(current_dir, "MJ_Avatar", "mj-1", "project.godot")

    if not os.path.exists(project_path):
        logger.warning(f"MJ Avatar project not found at: {project_path}")
        return False

    try:
        # Launch Godot with the avatar scene
        # The scene auto-starts the avatar with animations
        subprocess.Popen(
            [godot_exe, "--path", os.path.dirname(project_path), "--main-scene", "res://scenes/avatar.tscn"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("MJ Avatar (Godot) launched successfully with animations!")
        return True
    except FileNotFoundError:
        logger.warning("Godot executable not found in PATH.")
        logger.info("Install Godot from https://godotengine.org/download/windows/")
        return False
    except Exception as e:
        logger.error(f"Failed to launch Godot: {e}")
        return False


# ===========================================================================
# RUN COMMAND
# ===========================================================================

def run():
    """Launch both MJ Assistant and MJ Avatar (Godot) together."""
    print("\n" + "=" * 50)
    print("🚀 MJ Assistant — Starting up with Avatar...")
    print("=" * 50 + "\n")

    # Launch Godot avatar
    avatar_launched = _launch_godot_avatar()
    if avatar_launched:
        print("✅ MJ Avatar (3D model) launched with animations!")
        print("   The avatar will start with Standing Idle animation automatically.")
    else:
        print("⚠️  MJ Avatar could not be launched. Check Godot installation.")
        print("   Install from: https://godotengine.org/download/windows/")

    # Give Godot a moment to start
    time.sleep(2)

    # Start the main assistant loop
    main()


# ===========================================================================
# HOTKEY
# ===========================================================================

keyboard.add_hotkey("ctrl+alt+m", lambda: run_mj())


# ===========================================================================
# ENTRY POINT
# ===========================================================================

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        run()
    else:
        try:
            main()
        except Exception as e:
            print(f"\nCritical Error: {e}")
            report_error_to_mj(e)
            fix = input("\n[MJ] Error detect hua. Kya main ise fix karun? (y/n): ")
            if fix.lower() == "y":
                print("MJ is analyzing the code and preparing a fix...")
            else:
                print("Terminating...")
