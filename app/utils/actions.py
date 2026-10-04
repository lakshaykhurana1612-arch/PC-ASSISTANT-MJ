import os
import re
import time
import shutil
import datetime
import urllib.parse

from app.utils.browser_manager import browser_manager
import webbrowser
import psutil
import pyautogui
from app.utils.voice_duplex import start_duplex
from app.utils.voice import speak, listen

from app.utils.app_launcher import open_application
from app.utils.search import search_web
from app.utils.file_manager import (
    find_file,
    open_file,
    move_file,
    delete_file,
    read_text_file,
)

# NOTE: Some earlier code paths call `read_file`.
# Re-export it from `app.utils.file_manager` so callers can use the same name.
read_file = read_text_file



from app.developer.developer import analyze_project, find_function
from app.developer.developer_cache import save_cache, load_cache
from app.brain.groq_client import analyze_command_with_ai
from app.brain.pdf_groq import analyze_file
from app.utils.file_manager import find_best_pages_by_keyword

from app.utils.pdf_ai import (
    extract_pdf_page_text,
    extract_pdf_text_up_to_pages,
    )
from app.brain.pdf_groq import ask_groq_about_pdf

from app.utils.whatsapp import (
    send_whatsapp_message_background,
    send_whatsapp_file_background,
    send_whatsapp_message_background_by_name,
)
from app.utils.whatsapp import send_whatsapp_file, send_resume_via_whatsapp


# ==========================================================
# Path Shortcut Resolver
# ==========================================================

def _resolve_destination(dest: str) -> str:
    """Convert shortcuts like 'desktop', 'downloads' to full paths."""
    d = (dest or "").lower().strip()

    if d in ("desktop", "my desktop"):
        return os.path.join(os.path.expanduser("~"), "Desktop")
    if d in ("downloads", "my downloads"):
        return os.path.join(os.path.expanduser("~"), "Downloads")
    if d in ("documents", "my documents", "docs", "my docs"):
        return os.path.join(os.path.expanduser("~"), "Documents")
    if d in ("pictures", "my pictures", "photos"):
        return os.path.join(os.path.expanduser("~"), "Pictures")
    if d in ("music", "my music", "songs"):
        return os.path.join(os.path.expanduser("~"), "Music")
    if d in ("videos", "my videos"):
        return os.path.join(os.path.expanduser("~"), "Videos")

    # If it's already an absolute or drive path, use as-is
    if d.startswith(("c:", "d:", "e:", os.sep)):
        return dest

    maybe = os.path.join(os.path.expanduser("~"), dest)
    if os.path.exists(maybe):
        return maybe

    return dest


# ==========================================================
# Browser Registration
# ==========================================================

try:
    webbrowser.register(
        "chrome",
        None,
        webbrowser.BackgroundBrowser(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    )
except Exception:
    pass

try:
    webbrowser.register(
        "brave",
        None,
        webbrowser.BackgroundBrowser(r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"),
    )
except Exception:
    pass


# ==========================================================
# YouTube auto-play helper
# ==========================================================

def _youtube_auto_play():
    time.sleep(5)
    try:
        pyautogui.click(500, 400)
        time.sleep(0.5)
        for _ in range(30):
            pyautogui.press("tab")
            time.sleep(0.08)
        pyautogui.press("enter")
    except Exception as e:
        print(f"[YT AutoPlay] failed: {e}")


# ==========================================================
# AI Chat State — Smart Tab Reuse
# ==========================================================

_AI_CHAT_STATE = {
    "platform": None,      # "chatgpt" or "gemini"
    "tab_opened": False,   # Whether we've opened a tab for the current platform
}

# ChatGPT / Gemini input area coordinates (rough bottom-center where input field is)
_AI_CHAT_INPUT_COORDS = (500, 700)

def _handle_ai_chat(query: str, platform: str, force_new: bool = False) -> str:
    """
    Shared handler for AI Chat platforms (ChatGPT, Gemini, etc.).
    
    Features:
    - Smart tab reuse: if same platform, doesn't open new URL
    - Platform switching: closes old tab before opening new platform
    - Force new tab: via force_new=True
    
    Args:
        query: The search query to type
        platform: "chatgpt" or "gemini"
        force_new: If True, always open a new tab
        
    Returns:
        Response message string
    """
    global _AI_CHAT_STATE
    
    try:
        platform_lower = platform.lower()
        
        # Determine URL
        if "gemini" in platform_lower:
            url = "https://gemini.google.com"
            display_name = "Gemini"
        else:
            url = "https://chatgpt.com"
            display_name = "ChatGPT"
        
        # Check if we should reuse existing tab
        same_platform = (_AI_CHAT_STATE["platform"] == platform_lower and _AI_CHAT_STATE["tab_opened"])
        
        if same_platform and not force_new:
            # ---- REUSE EXISTING TAB ----
            # Don't open URL, just click on existing page to focus,
            # select all existing text, type new query, submit
            time.sleep(0.5)
            pyautogui.click(*_AI_CHAT_INPUT_COORDS)  # Click input area
            time.sleep(0.5)
            pyautogui.hotkey("ctrl", "a")              # Select all existing text
            time.sleep(0.2)
            pyautogui.press("delete")                  # Clear it
            time.sleep(0.2)
            pyautogui.write(query, interval=0.03)
            time.sleep(0.3)
            pyautogui.press("enter")
            return f"{display_name} tab reuse kar diya Boss. {query[:50]} search kar rahi hoon."
        
        else:
            # ---- NEW TAB or PLATFORM SWITCH ----
            # If switching platform, close old tab first
            if _AI_CHAT_STATE["tab_opened"] and _AI_CHAT_STATE["platform"] != platform_lower:
                pyautogui.hotkey("ctrl", "w")
                time.sleep(0.5)
            
            # Open new URL
            webbrowser.open(url)
            _AI_CHAT_STATE["platform"] = platform_lower
            
            # Wait for page to load
            load_time = 6
            time.sleep(load_time)
            
            # Click and type query
            pyautogui.click(*_AI_CHAT_INPUT_COORDS)
            time.sleep(0.5)
            
            if query:
                pyautogui.write(query, interval=0.03)
                time.sleep(0.3)
                pyautogui.press("enter")
            
            _AI_CHAT_STATE["tab_opened"] = True
            return f"{display_name} khol diya Boss. Query type kar rahi hoon."
    
    except Exception as e:
        return f"{platform} operation failed: {e}"


# ==========================================================
# Main Action Handler
# ==========================================================

def execute_smart_action(ai_decision, user_input=""):
    if not ai_decision:
        return None

    chat_responses: list[str] = []

    raw_steps = ai_decision.split("&&")
    steps: list[str] = []
    for item in raw_steps:
        item = item.strip()
        if item and item not in steps:
            steps.append(item)

    for step in steps:
        # ---------------- FILE SEARCH ----------------
        if step.startswith("FILE_SEARCH:"):
            query = step.replace("FILE_SEARCH:", "").strip()
            try:
                path = find_file(query)
                if path:
                    open_file(path)
                    chat_responses.append(f"Boss, file mil gayi! {os.path.basename(path)}")
                else:
                    chat_responses.append(f"Boss, '{query}' naam ki koi file nahi mili.")

            except Exception as e:
                chat_responses.append(f"File search failed: {e}")

        # ---------------- WEB SEARCH ----------------
        elif step.startswith("SEARCH:"):
            query = step.replace("SEARCH:", "").strip()
            try:
                chat_responses.append(search_web(query))
            except Exception as e:
                chat_responses.append(f"Search failed: {e}")

        # ---------------- YOUTUBE / WEBSITES ----------------
        elif step.startswith("BRAVE_YOUTUBE:"):
            query = step.replace("BRAVE_YOUTUBE:", "").strip()
            url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
            try:
                webbrowser.get("brave").open(url)
            except Exception:
                webbrowser.open(url)
            _youtube_auto_play()

        elif step.startswith("YOUTUBE_SEARCH:"):
            query = step.replace("YOUTUBE_SEARCH:", "").strip()
            url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
            webbrowser.open(url)

        elif step.startswith("YOUTUBE:"):
            query = step.replace("YOUTUBE:", "").strip()
            url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
            webbrowser.open(url)
            _youtube_auto_play()

        elif step.startswith("BRAVE_WEBSITE:"):
            raw_text = step.replace("BRAVE_WEBSITE:", "").strip()
            match = re.search(r"https?://[^\s,]+", raw_text)
            try:
                if match:
                    webbrowser.get("brave").open(match.group(0))
                else:
                    webbrowser.get("brave").open(
                        "https://www.google.com/search?q=" + urllib.parse.quote(raw_text)
                    )
            except Exception:
                webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(raw_text))

        elif step.startswith("OPEN_WEBSITE:"):
            raw_text = step.replace("OPEN_WEBSITE:", "").strip()
            match = re.search(r"https?://[^\s,]+", raw_text)
            if match:
                webbrowser.open(match.group(0))
            else:
                webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(raw_text))

        # ---------------- WHATSAPP ----------------
        elif step.startswith("WHATSAPP_MSG:"):
            try:
                data = step.replace("WHATSAPP_MSG:", "").strip()
                if "|" not in data:
                    chat_responses.append("Invalid WhatsApp format.")
                    continue
                target_name, message = [x.strip() for x in data.split("|", 1)]
                webbrowser.open("https://web.whatsapp.com")
                time.sleep(12)
                pyautogui.hotkey("ctrl", "alt", "/")
                time.sleep(1)
                pyautogui.write(target_name, interval=0.03)
                time.sleep(2)
                pyautogui.press("enter")
                time.sleep(2)
                pyautogui.write(message, interval=0.02)
                pyautogui.press("enter")
                chat_responses.append(f"WhatsApp message sent to {target_name}.")
            except Exception as e:
                chat_responses.append(f"WhatsApp Error: {e}")

        elif step.startswith("WHATSAPP_FILE:"):
            try:
                data = step.replace("WHATSAPP_FILE:", "").strip()
                if "|" not in data:
                    chat_responses.append("Invalid WHATSAPP_FILE format.")
                    continue
                contact, filename = map(str.strip, data.split("|", 1))
                send_whatsapp_file(contact, filename)
            except Exception as e:
                chat_responses.append(f"WHATSAPP_FILE error: {e}")

        elif step.startswith("BG_WHATSAPP_MSG:"):
            try:
                data = step.replace("BG_WHATSAPP_MSG:", "").strip()
                if "|" not in data:
                    chat_responses.append("Invalid Background WhatsApp format.")
                    continue
                contact, message = [x.strip() for x in data.split("|", 1)]
                if contact and any(ch.isdigit() for ch in contact) and all(
                    (c.isdigit() or c in '+- ()') for c in contact
                ):
                    chat_responses.append(send_whatsapp_message_background(contact, message))
                else:
                    send_whatsapp_message_background_by_name(contact, message)
                    chat_responses.append(f"WhatsApp message sending started for {contact} (name).")
            except Exception as e:
                chat_responses.append(f"Background WhatsApp Error: {e}")

        elif step.startswith("BG_WHATSAPP_FILE:"):
            try:
                data = step.replace("BG_WHATSAPP_FILE:", "").strip()
                if "|" not in data:
                    chat_responses.append("Invalid Background WhatsApp File format.")
                    continue
                contact, filename = [x.strip() for x in data.split("|", 1)]
                chat_responses.append(send_whatsapp_file_background(contact, filename))
            except Exception as e:
                chat_responses.append(f"Background WhatsApp File Error: {e}")

        # ---------------- CONTROL ----------------
        # ---------------- OPEN CHATGPT (with or without colon) ----------------
        elif step == "OPEN_CHATGPT" or step.startswith("OPEN_CHATGPT:"):
            data = step.split("OPEN_CHATGPT:", 1)[1].strip() if ":" in step else ""
            try:
                result = _handle_ai_chat(query=data, platform="chatgpt", force_new=False)
                chat_responses.append(result)
            except Exception as e:
                chat_responses.append(f"ChatGPT operation failed: {e}")

        # ---------------- OPEN GEMINI (with or without colon) ----------------
        elif step == "OPEN_GEMINI" or step.startswith("OPEN_GEMINI:"):
            data = step.split("OPEN_GEMINI:", 1)[1].strip() if ":" in step else ""
            try:
                result = _handle_ai_chat(query=data, platform="gemini", force_new=False)
                chat_responses.append(result)
            except Exception as e:
                chat_responses.append(f"Gemini operation failed: {e}")

        # ---------------- OPEN CHATAI alias (with or without colon) ----------------
        elif step == "OPEN_CHATAI" or step.startswith("OPEN_CHATAI:"):
            data = step.split("OPEN_CHATAI:", 1)[1].strip() if ":" in step else ""
            try:
                result = _handle_ai_chat(query=data, platform="chatgpt", force_new=False)
                chat_responses.append(result)
            except Exception as e:
                chat_responses.append(f"ChatAI operation failed: {e}")

        # ---------------- OPEN CHATGPT NEW TAB (force new tab) ----------------
        elif step.startswith("OPEN_CHATGPT_NEW:"):
            try:
                data = step.replace("OPEN_CHATGPT_NEW:", "").strip()
                result = _handle_ai_chat(query=data, platform="chatgpt", force_new=True)
                chat_responses.append(result)
            except Exception as e:
                chat_responses.append(f"ChatGPT new tab failed: {e}")

        # ---------------- OPEN GEMINI NEW TAB (force new tab) ----------------
        elif step.startswith("OPEN_GEMINI_NEW:"):
            try:
                data = step.replace("OPEN_GEMINI_NEW:", "").strip()
                result = _handle_ai_chat(query=data, platform="gemini", force_new=True)
                chat_responses.append(result)
            except Exception as e:
                chat_responses.append(f"Gemini new tab failed: {e}")

        elif step.startswith("CLOSE_TAB"):
            try:
                pyautogui.hotkey("ctrl", "w")
                chat_responses.append("Tab closed.")
            except Exception as e:
                chat_responses.append(f"Close tab failed: {e}")
        # ==================================================
        # DUPLEX MODE (legacy)
        # ==================================================

        elif step.startswith("DUPLEX_MODE"):

            start_duplex()

            return "Duplex Closed."

        # (FireRed Duplex commands removed)
        # ---------------- FILE MOVE/DELETE ----------------
        elif step.startswith("FILE_MOVE:"):
            try:
                data = step.replace("FILE_MOVE:", "").strip()
                if "|" not in data:
                    chat_responses.append(
                        "Invalid FILE_MOVE format. Use: FILE_MOVE: filename | destination"
                    )
                    continue
                query, dest = [x.strip() for x in data.split("|", 1)]
                path = find_file(query)
                if not path:
                    chat_responses.append(f"Boss, '{query}' nahi mili.")
                    continue
                dest = _resolve_destination(dest)
                success, msg = move_file(path, dest)
                chat_responses.append(f"Boss, {msg}" if success else f"Error: {msg}")
            except Exception as e:
                chat_responses.append(f"File move failed: {e}")

        elif step.startswith("FILE_DELETE:"):
            try:
                query = step.replace("FILE_DELETE:", "").strip()
                path = find_file(query)
                if not path:
                    chat_responses.append(f"Boss, '{query}' nahi mili.")
                    continue
                success, msg = delete_file(path)
                chat_responses.append(f"Boss, {msg}" if success else f"Error: {msg}")
            except Exception as e:
                chat_responses.append(f"File delete failed: {e}")

        # ---------------- PROJECT ANALYZER ----------------
        elif step.startswith("ANALYZE_PROJECT"):
            try:
                result = analyze_project("D:/MJ")
                save_cache(result)
                return (
                    "📊 Project Analysis Complete!\n\n"
                    f"📁 Project : {result['project']}\n"
                    f"📂 Folders : {result['folders']}\n"
                    f"📄 Files : {result['files']}\n"
                    f"🐍 Python Files : {result['python']}\n"
                    f"⚙ Functions : {result['functions']}\n"
                    f"🏛 Classes : {result['classes']}\n"
                    f"📦 Imports : {result['imports']}\n\n"
                    "Top Functions:\n"
                    + "\n".join(result["function_names"][:10])
                    + "\n\nTop Classes:\n"
                    + "\n".join(result["class_names"][:10])
                )
            except Exception as e:
                return f"Project analysis failed: {e}"

        elif step.startswith("FIND_FUNCTION:"):
            name = step.replace("FIND_FUNCTION:", "").strip()
            data = load_cache()
            func = find_function(data, name)
            if func:
                return (
                    f"Function : {func['name']}\n"
                    f"File : {func['file']}\n"
                    f"Line : {func['line']}\n"
                    f"Arguments : {', '.join(func['args'])}"
                )
            return "Function not found."

        # ==========================================================
        # PDF AI COMMANDS
        # ==========================================================
        # FILE READ (plain text) + explain/summarise
        # ==========================================================
        elif step.startswith("FILE_READ:"):

            try:
                data = step.replace("FILE_READ:", "").strip()

                # Format:
                # FILE_READ: filename
                # FILE_READ: filename | user question
                if "|" in data:
                    file_query, user_req = [x.strip() for x in data.split("|", 1)]
                else:
                    file_query = data
                    user_req = "Read and summarize this file."

                file_path = find_file(file_query) if file_query else None

                if not file_path:
                    chat_responses.append("Boss, file nahi mila.")
                    continue

                ext = os.path.splitext(file_path)[1].lower()

                # PDF
                if ext == ".pdf":
                    ai_text = analyze_file(
                        filename=file_query,
                        user_request=user_req
                    )
                    chat_responses.append(ai_text)
                    continue

                # Normal text files
                text = read_file(file_path)

                ai_text = analyze_command_with_ai(
                    f"""
You are reading a local file.

File Name:
{os.path.basename(file_path)}

User Request:
{user_req}

========== FILE CONTENT ==========
{text}
========== END ==========
"""
                )

                chat_responses.append(ai_text)

            except Exception as e:
                chat_responses.append(f"FILE_READ failed: {e}")
        # ---------------- CHAT ----------------
        elif step.startswith("CHAT:"):
            continue

        elif step.startswith("OPEN_APPLICATION:"):
            app_name = step.replace("OPEN_APPLICATION:", "").strip()
            open_application(app_name)

        elif step.startswith("RESTART_SYSTEM"):
            try:
                # Check if code was provided inline (e.g. RESTART_SYSTEM:10)
                rest = step[len("RESTART_SYSTEM"):].strip()
                if rest.startswith(":") and rest[1:].strip().isdigit():
                    code = rest[1:].strip()
                else:
                    speak("Boss, restart karne ke liye code boliye.")
                    code = listen()
                    if not code:
                        chat_responses.append("Code nahi suna. Operation cancelled.")
                        continue

                if code.strip() == "10":
                    speak("Code sahi hai. Restart kar rahi hoon Boss.")
                    os.system("shutdown /r /t 1")
                else:
                    chat_responses.append("Code galat hai. Operation cancelled.")
            except Exception as e:
                chat_responses.append(f"Restart failed: {e}")

        elif step.startswith("SHUTDOWN_SYSTEM"):
            try:
                # Check if code was provided inline (e.g. SHUTDOWN_SYSTEM:10)
                rest = step[len("SHUTDOWN_SYSTEM"):].strip()
                if rest.startswith(":") and rest[1:].strip().isdigit():
                    code = rest[1:].strip()
                else:
                    speak("Boss, shutdown karne ke liye code boliye.")
                    code = listen()
                    if not code:
                        chat_responses.append("Code nahi suna. Operation cancelled.")
                        continue

                if code.strip() == "10":
                    speak("Code sahi hai. Shut down kar rahi hoon Boss.")
                    os.system("shutdown /s /t 1")
                else:
                    chat_responses.append("Code galat hai. Operation cancelled.")
            except Exception as e:
                chat_responses.append(f"Shutdown failed: {e}")

        elif step.startswith("CLOSE_SPECIFIC_TABS:"):
            try:
                hint = step.split("CLOSE_SPECIFIC_TABS:", 1)[1].strip().lower()
                if "chrome" in hint:
                    os.system("taskkill /IM chrome.exe /F")
                    chat_responses.append("Chrome ko hard close kar diya.")
                elif "brave" in hint:
                    os.system("taskkill /IM brave.exe /F")
                    chat_responses.append("Brave ko hard close kar diya.")
                elif "edge" in hint:
                    os.system("taskkill /IM msedge.exe /F")
                    chat_responses.append("Edge ko hard close kar diya.")
                else:
                    pyautogui.hotkey("ctrl", "w")
                    chat_responses.append(f"{hint} ke tabs band kar diye (active tab close).")
            except Exception as e:
                chat_responses.append(f"Close specific tabs failed: {e}")

        elif step.startswith("STOP_BACKGROUND_BROWSER"):
            browser_manager.stop_browser()
            chat_responses.append("Background browser engine stopped.")

        else:
            print(f"[MJ] Unknown Command -> {step}")

    if chat_responses:
        return " ".join(chat_responses)

    return None

