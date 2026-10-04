# MJ Assistant — Architecture (High + Implementation Details)

> This document describes the runtime architecture, module responsibilities, and the concrete tag-to-action execution model used by the project.

---

## 1) System Overview

MJ is a voice-enabled desktop assistant that:
1. Listens for a user command (keyboard input and/or wake-word).
2. Sends the command to an LLM (“MJ SYSTEM PROMPT” forces a strict tagged output).
3. Parses the LLM output tags (e.g., `FILE_SEARCH:`, `YOUTUBE:`).
4. Executes OS/browser/WhatsApp/file operations locally.
5. Speaks back results using TTS.

---

## 2) Core Modules (A+B: responsibilities + how they work)

### 2.1 Entry / Orchestration

#### `main.py`
**Role:** Runtime loop and “orchestrator”.
- Initializes environment (`dotenv`).
- Exposes:
  - `run_mj(user_input=None)` for hotkey/wake use.
  - `main()` interactive loop (text input; empty input triggers voice listen()).
  - `process_command(command)` (older helper / partial logic).

**Important runtime flow:**
- Obtain `user_input` (typed or transcribed).
- Call `analyze_command_with_ai(user_input)`.
- Receive `ai_decision` which must contain tags.
- Handle:
  - `FILE_SEARCH:` directly in some code paths.
  - `SEARCH:` via web-search + LLM summarization.
  - Otherwise delegate to `execute_smart_action(ai_decision)`.

> Note: `main.py` mixes multiple flows (`run_mj` vs `main()` loop). Architecture below explains the *intended* unified flow: AI tags → executor.

#### `app/utils/wake_word.py`
**Role:** Wake-word loop.
- Uses `listen_wake()` from `voice.py`.
- When transcript starts with `mj`, it calls `from main import run_mj` and executes the remainder as a normal command.

---

### 2.2 “Brain” / LLM Decision Engine

#### `app/brain/groq_client.py`
**Role:** LLM client with fallback chain + conversation memory.

**Key responsibilities:**
- Load `.env` API keys.
  - Primary: `GEMINI_API_KEY`
  - Backup: `GEMINI_API_KEY_2`
  - Third: `GROQ_API_KEY`
- Maintain `conversation_history` (includes system prompt).
- Build LLM request payload in Gemini format.
- Implement fallback behavior:
  1. Try Gemini primary.
  2. If fails, try Gemini backup.
  3. If that fails, try Groq model `openai/gpt-oss-120b`.
- Return `ai_response` as strict tagged text.

**Failure handling (implementation detail):**
- Detect errors by string matching:
  - Quota/rate limit (`429`, `quota`, `resource_exhausted`) → fallback chain.
  - Server overload (`503`, `unavailable`) → retry after sleep.
  - Network issues (`connection`, `timeout`, `network`) → returns a `CHAT:` message.

---

### 2.3 System Prompt Contract (Tag Protocol)

#### `app/prompts/mj_system.txt`
**Role:** Defines the hard contract for every LLM response.

**Contract rules:**
- Every response must begin with one of the allowed tags (e.g., `CHAT:`, `FILE_SEARCH:`, `YOUTUBE:`...).
- Multi-step operations must be separated with `&&`.
- The prompt includes priority rules for command decision and strict anti-hallucination.

This contract is crucial because the executor (`actions.py`) is a tag interpreter.

---

### 2.4 Action Executor (Tag interpreter)

#### `app/utils/actions.py`
**Role:** Converts LLM tags → real side effects (files/web/WhatsApp/system).

**Main entry:** `execute_smart_action(ai_decision)`

**Execution model:**
1. Split `ai_decision` by `&&`.
2. De-duplicate steps.
3. For each `step`, call the corresponding handler based on prefix.

**Tag-to-handler examples (implementation detail):**
- `FILE_SEARCH:`
  - Uses `find_file(query)` to locate a local file.
  - Opens it via `open_file(path)`.
- `SEARCH:`
  - Calls `search_web(query)` and appends raw returned snippet.
- `OPEN_WEBSITE:`
  - Extracts a URL if present; otherwise performs a Google search URL.
- `BRAVE_WEBSITE:`
  - Same as website, but tries `webbrowser.get('brave')`.
- `YOUTUBE:` / `BRAVE_YOUTUBE:`
  - Opens YouTube search results page.
  - Then runs `_youtube_auto_play()` which uses `pyautogui` tab navigation + Enter.
- WhatsApp:
  - `WHATSAPP_MSG:` uses WhatsApp Web UI automation (pyautogui + sleep).
  - `WHATSAPP_FILE:` calls `send_whatsapp_file(contact, filename)`.
  - `BG_WHATSAPP_MSG:` / `BG_WHATSAPP_FILE:` routes to background helper functions.
- File operations:
  - `FILE_MOVE:` resolves shortcut destinations (desktop/downloads/etc) and moves.
  - `FILE_DELETE:` locates and deletes.
- System:
  - `RESTART_SYSTEM` / `SHUTDOWN_SYSTEM` uses password prompt + `os.system('shutdown ...')`.
  - `STOP_BACKGROUND_BROWSER` calls `browser_manager.stop_browser()`.

---

### 2.5 File System Utilities

#### `app/utils/file_manager.py`
**Role:** Local filesystem operations.

**Key functions:**
- `get_drives()` enumerates existing Windows drives.
- `find_file(query)`:
  - Walks drives recursively (`os.walk`).
  - Skips dangerous/system folders via `skip_folders`.
  - Matches if **all query words** exist in lowercase filename.
- `open_file(path)` uses `os.startfile`.
- `move_file(source_path, dest_folder)` uses `shutil.move` and adds suffixes if collision.
- `delete_file(file_path)` uses `os.remove`.
- Security helpers:
  - Reads `MJ_PASSWORD` from env.
  - `secure_overwrite(...)` and `apply_patch(...)` require password input.

---

### 2.6 Web Search

#### `app/utils/search.py`
**Role:** Internet search.
- Uses `ddgs.DDGS()`.
- Returns the first result’s `body` snippet.

> This is used by the `SEARCH:` tag path.

---

### 2.7 Voice I/O

#### `app/utils/voice.py`
**Role:** Speech-to-text and text-to-speech.

**TTS (`speak`)**
- Uses `edge_tts` to generate an MP3.
- Plays MP3 via `pygame.mixer`.
- Auto-selects a Hindi voice if Devanagari characters exist.
- Cleans up the temporary MP3 after playback.

**STT (`listen`)**
- Uses `speech_recognition` + Google recognizer.
- Records for `CAPTURE_SECONDS` into `debug.wav`.
- Calls `recognize_google(audio)`.

**Wake STT (`listen_wake`)**
- Short-phrase listening with timeout and phrase limit.

---

### 2.8 Background Browser Automation

#### `app/utils/browser_manager.py`
**Role:** Manage Playwright instances for background tasks.
- Uses `playwright.sync_api`.
- Has:
  - `start_browser()`
  - `stop_browser()` (saves storage_state per context)
  - `get_page(context_name)` creates/reuses a context with persisted `state.json`.

---

### 2.9 WhatsApp Integration

#### `app/utils/whatsapp.py`
**Role:** Send WhatsApp messages/files.

**Main behaviors:***
- `send_whatsapp_file(contact_name, filename)`
  - Opens WhatsApp Web.
  - Searches contact via Ctrl+Alt+/.
  - Attaches file (Ctrl+Shift+A) then types file path.
  - Sends via Enter.
- `send_resume_via_whatsapp` is a wrapper.

**Background-ish helpers:**
- `send_whatsapp_message_background(contact_number, message)` uses `pywhatkit.sendwhatmsg_instantly` in a daemon thread.
- `send_whatsapp_message_background_by_name(contact_name, message)` uses WhatsApp Web UI automation in a thread and retries.
- `send_whatsapp_file_background(contact_number, file_path)` uses UI automation with a daemon thread and attaches via tab/enter navigation.

> Important: despite “background”, many paths still drive UI through automation and rely on timing.

---

### 2.10 Error Tracking

#### `app/utils/error_manager.py`
**Role:** Store last error context and optionally delegate analysis to AI.

**Capabilities:**
- `save_error(...)` and `get_error()` store `LAST_ERROR/LAST_COMMAND/LAST_MODULE`.
- `report_error_to_mj(error, file_path)` reads code content and calls AI.

---

## 3) End-to-End Data Flow (B: concrete sequences)

### Sequence: Normal command
1. `main.main()` waits for user input.
2. If empty → `voice.listen()` produces `user_input`.
3. `groq_client.analyze_command_with_ai(user_input)` generates tagged `ai_decision`.
4. `actions.execute_smart_action(ai_decision)` parses tags and performs:
   - File search + open
   - Web/youtube open and UI automation
   - WhatsApp send
   - Moves/deletes
5. `main` speaks the returned chat response(s) via `voice.speak()`.

### Sequence: Wake-word command
1. `wake_word_loop()` calls `listen_wake()`.
2. If transcript starts with `mj`, calls `main.run_mj(command)`.
3. Same AI decision + action execution flow as above.

---

## 4) Tag Parsing Rules (B: critical implementation contract)

### 4.1 Multi-step delimiter
- LLM must output multiple actions separated by `&&`.
- Executor expects that separator in `execute_smart_action`.

### 4.2 Step de-duplication
- `actions.execute_smart_action` removes repeated identical steps.

### 4.3 Prefix dispatch
- Executor dispatch is performed purely by `step.startswith("TAG:")`.

**Implication:** If the LLM outputs `TAG :` or formatting deviates from prompt, the executor may treat it as unknown.

---

## 5) System Boundaries & Dependencies

### Local side effects
- Filesystem: `os.walk` search across drives, file open/move/delete.
- Browser/UI automation:
  - `webbrowser.open()`
  - `pyautogui` for tab/enter/click sequences
- WhatsApp:
  - UI automation + pywhatkit.
- System actions:
  - `os.system('shutdown ...')`.

### Network dependencies
- STT via Google in `recognize_google`.
- LLM calls to Gemini/Groq.
- Web search via DDGS.

---

## 6) Architectural Issues / Risks (useful for future refactor)

- `main.py` appears to contain duplicated / partially diverging orchestration paths (`run_mj` vs `main`).
- `actions.py` imports background WhatsApp functions from `app.utils.whatsapp` but the prompt indicates “Playwright moved to app/browser/...”; current repo places logic directly in `app/utils/whatsapp.py` (possible mismatch).
- `error_manager.report_error_to_mj(...)` signature differs from some call sites shown in `main.py` (in `main.py` the call is `report_error_to_mj(e)` but the function expects `(error, file_path)`), which can break error reporting.
- `find_file()` is very expensive (walks all drives). This can cause latency and may impact UX.

---

## 7) Suggested “Ideal” Layering (for understanding)

1. **Presentation / Input Layer**
   - `main.py`, `wake_word.py`, `voice.py`
2. **Decision Layer (LLM contract)**
   - `groq_client.py`, `mj_system.txt`
3. **Execution Layer (tag interpreter)**
   - `actions.py`
4. **Integration Layer (capabilities)**
   - `file_manager.py`, `search.py`, `whatsapp.py`, `browser_manager.py`
5. **Observability / Error Layer**
   - `error_manager.py`

---

## 8) Appendix: Where to look next
- Tag interpreter: `app/utils/actions.py`
- LLM fallback logic: `app/brain/groq_client.py`
- System output contract: `app/prompts/mj_system.txt`
- File operations: `app/utils/file_manager.py`
- Voice: `app/utils/voice.py`
- WhatsApp automation: `app/utils/whatsapp.py`

