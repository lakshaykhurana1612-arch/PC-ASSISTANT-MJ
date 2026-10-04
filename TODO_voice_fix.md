# Voice Start Function Fix Plan

## Issue
Voice "start voice" / "voice on" command isn't working properly. Multiple race conditions and logic bugs in `VoiceAssistant`.

## Steps

- [x] 1. Fix `_audio_loop` vs `_process_loop` conflict in `voice_assistant.py`
- [x] 2. Fix `start()` to return bool and propagate VAD init failure
- [x] 3. Add `start_conversation()` method for atomic startup
- [x] 4. Fix `_process_loop` timeout race: set `_last_speech_time` before threads start
- [x] 5. Fix webrtcvad frame size comment (confirmed: 480 samples = 960 bytes = correct)
- [x] 6. Update `_handle_system_command` in `main.py` to use new API with return value check
- [ ] 7. Test the application

