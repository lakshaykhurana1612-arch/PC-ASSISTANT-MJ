# TTS PermissionError Fix — Todo

## Issue
`PermissionError: [Errno 13] Permission denied: 'mj_voice.mp3'` in duplex mode when TTS is interrupted.

## Steps

- [x] 1. Fix `app/utils/voice.py` — Use unique temp filenames + retry logic for unlink + graceful PermissionError handling
- [x] 2. Fix `app/utils/duplex_voice.py` — Add `pygame.mixer.music.unload()` after stop to release file handle
- [x] 3. Fix `app/voice_engine/voice_assistant.py` — Use unique temp filenames + better cleanup
- [x] 4. Fix `app/voice_engine/tts.py` — Use unique temp filenames + `_close_files` with retry logic
- [x] 5. Test the application

