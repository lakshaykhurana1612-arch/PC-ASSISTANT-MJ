import webbrowser
import time
import os
import threading
import pyautogui
import pywhatkit
from datetime import datetime

from app.utils.file_manager import find_file

# This file is now for PyAutoGUI-based WhatsApp functions.
# The Playwright background functions have been moved to app/browser/whatsapp.py
# Add your existing PyAutoGUI functions for send_whatsapp_file and send_resume_via_whatsapp here.

def send_whatsapp_file(contact_name: str, filename: str):
    """Sends a file to a WhatsApp contact using PyAutoGUI."""
    print(f"[WhatsApp] Sending file '{filename}' to '{contact_name}'...")

    file_path = find_file(filename)
    if not file_path:
        print(f"[WhatsApp] Error: File '{filename}' not found.")
        return f"Boss, file '{filename}' nahi mili."

    try:
        webbrowser.open("https://web.whatsapp.com")
        time.sleep(15)  # Wait for WhatsApp Web to load

        # Search for contact
        pyautogui.hotkey("ctrl", "alt", "/")
        time.sleep(1)
        pyautogui.write(contact_name, interval=0.03)
        time.sleep(2)
        pyautogui.press("enter")
        time.sleep(2)

        # Attach file
        pyautogui.hotkey("ctrl", "shift", "a") # Shortcut for attachment
        time.sleep(2)
        pyautogui.write(file_path, interval=0.02)
        time.sleep(1)
        pyautogui.press("enter")
        time.sleep(2)

        # Send
        pyautogui.press("enter")
        time.sleep(2)

        pyautogui.hotkey("ctrl", "w") # Close tab

        print(f"[WhatsApp] File sent to {contact_name}.")
        return f"File sent to {contact_name}."
    except Exception as e:
        print(f"[WhatsApp] Error sending file: {e}")
        return f"Failed to send file: {e}"

def send_resume_via_whatsapp(contact_name: str, file_path: str):
    """Wrapper function to send a resume file."""
    return send_whatsapp_file(contact_name, file_path)




def send_whatsapp_message_background(contact_number, message):
    """
    Background mein WhatsApp message bhejne ke liye function.
    contact_number: '+91xxxxxxxxxx' format mein hona chahiye.
    """
    def send_task():
        try:
            # Current time se 2 minute baad ka time set karna zaroori hai pywhatkit ke liye
            now = datetime.now()
            hour = now.hour
            minute = now.minute + 2
            
            # Message bhejne ki command
            pywhatkit.sendwhatmsg_instantly(
                phone_no=contact_number, 
                message=message,
                wait_time=15,
                tab_close=True
            )
            print(f"✅ Message sent to {contact_number}")
        except Exception as e:
            print(f"❌ Failed to send WhatsApp message: {e}")

    # Function ko alag thread mein chalao
    threading.Thread(target=send_task, daemon=True).start()


import pyautogui
import pywhatkit
import time
import threading
import os


def _is_phone_like(s: str) -> bool:
    if not s:
        return False
    x = s.strip()
    # allows +, digits, spaces, hyphen
    return any(c.isdigit() for c in x) and all((c.isdigit() or c in '+- ()') for c in x)


WHATSAPP_UI_LOCK = threading.Lock()


def send_whatsapp_message_background_by_name(contact_name: str, message: str):
    """Send message using WhatsApp Web UI search by contact NAME.

    Note: This is not truly headless background messaging; it still drives the UI.
    To make it more reliable, we: 
    - lock UI sending (prevents MJ from typing at same time)
    - retry the send a few times
    """

    def task():
        # Prevent multiple concurrent UI automations
        with WHATSAPP_UI_LOCK:
            last_err = None
            for attempt in range(3):
                try:
                    webbrowser.open("https://web.whatsapp.com")
                    time.sleep(15)

                    # Focus WhatsApp search
                    pyautogui.hotkey("ctrl", "alt", "/")
                    time.sleep(1)

                    pyautogui.write(contact_name, interval=0.03)
                    time.sleep(2)
                    pyautogui.press("enter")
                    time.sleep(2)

                    pyautogui.write(message, interval=0.02)
                    pyautogui.press("enter")

                    print(f"✅ WhatsApp message sent to '{contact_name}'")
                    return f"WhatsApp message sent to {contact_name}."
                except Exception as e:
                    last_err = e
                    print(f"❌ Failed WhatsApp(name) send attempt {attempt+1}: {e}")
                    # small wait before retry
                    time.sleep(3)

            return f"Failed to send WhatsApp message to {contact_name}: {last_err}"

    threading.Thread(target=task, daemon=True).start()



def send_whatsapp_file_background(contact_number, file_path):
    """
    Background mein WhatsApp file bhejne ke liye function.
    """
    def file_task():
        try:
            # 1. Pehle chat open karo
            pywhatkit.sendwhatmsg_instantly(contact_number, "Sending file...", wait_time=10, tab_close=False)
            time.sleep(5) # WhatsApp Web load hone ka wait
            
            # 2. File attach button par click karo (Coordinates screen ke hisaab se adjust karna)
            # Yahan hum UI automation use kar rahe hain
            pyautogui.press('tab', presses=5) # Attach button tak jaane ke liye
            pyautogui.press('enter')
            
            # 3. File path paste karo
            pyautogui.write(os.path.abspath(file_path))
            pyautogui.press('enter')
            time.sleep(2)
            
            # 4. Send button
            pyautogui.press('enter')
            print(f"✅ File {file_path} sent to {contact_number}")
            
        except Exception as e:
            print(f"❌ Failed to send file: {e}")

    # Threading start
    threading.Thread(target=file_task, daemon=True).start()
