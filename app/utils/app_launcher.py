import os
import subprocess

# ==========================================================
# WINDOWS APPLICATION DATABASE
# ==========================================================

APP_COMMANDS = {

    # ---------- Windows ----------
    "calculator": "calc.exe",
    "calc": "calc.exe",

    "notepad": "notepad.exe",

    "paint": "mspaint.exe",

    "cmd": "cmd.exe",

    "command prompt": "cmd.exe",

    "powershell": "powershell.exe",

    "terminal": "wt.exe",

    "windows terminal": "wt.exe",

    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",

    "task manager": "taskmgr.exe",

    "registry editor": "regedit.exe",

    "control panel": "control.exe",

    "device manager": "devmgmt.msc",

    "disk management": "diskmgmt.msc",

    "services": "services.msc",

    "event viewer": "eventvwr.msc",

    "system configuration": "msconfig.exe",

    "resource monitor": "resmon.exe",

    "performance monitor": "perfmon.msc",

    "snipping tool": "snippingtool.exe",

    "character map": "charmap.exe",

    "on screen keyboard": "osk.exe",

    "magnifier": "magnify.exe",

    "wordpad": "write.exe",

    # ---------- Browsers ----------
    "chrome": "chrome.exe",

    "brave": "brave.exe",

    "edge": "msedge.exe",

    "firefox": "firefox.exe",

    # ---------- Editors ----------
    "vs code": "Code.exe",
    "vscode": "Code.exe",

    "cursor": "Cursor.exe",

    "pycharm": "pycharm64.exe",

    "intellij": "idea64.exe",

    "android studio": "studio64.exe",

    # ---------- Communication ----------
    "discord": "Discord.exe",

    "telegram": "Telegram.exe",

    "whatsapp": "WhatsApp.exe",

    # ---------- Media ----------
    "spotify": "Spotify.exe",

    "vlc": "vlc.exe",

    "obs": "obs64.exe",

    # ---------- Gaming ----------
    "steam": "steam.exe",

    "epic games": "EpicGamesLauncher.exe",

    # ---------- Adobe ----------
    "photoshop": "Photoshop.exe",

    "illustrator": "Illustrator.exe",

    "premiere pro": "Adobe Premiere Pro.exe",

    "after effects": "AfterFX.exe"
}

# ==========================================================
# UWP APPS
# ==========================================================

UWP_APPS = {

    "settings": "ms-settings:",

    "windows settings": "ms-settings:",

    "calculator": "calculator:",

    "camera": "microsoft.windows.camera:",

    "store": "ms-windows-store:",

    "microsoft store": "ms-windows-store:",

    "mail": "outlookmail:",

}

# ==========================================================
# OPEN APPLICATION
# ==========================================================

def open_application(app_name: str):

    app = app_name.lower().strip()

    # ------------------------------
    # UWP Apps
    # ------------------------------

    if app in UWP_APPS:

        try:

            os.startfile(UWP_APPS[app])

            print(f"[MJ] Opened {app}")

            return True

        except Exception as e:

            print(f"[MJ] Failed: {e}")

            return False

    # ------------------------------
    # Normal Windows Apps
    # ------------------------------

    if app in APP_COMMANDS:

        try:

            os.system(f'start "" "{APP_COMMANDS[app]}"')
            shell=True,
            creationflags=subprocess.CREATE_NEW_CONSOLE
            
            print(f"[MJ] Opened {app}")

            return True

        except Exception as e:

            print(f"[MJ] Failed: {e}")

    # ------------------------------
    # Direct command fallback
    # ------------------------------

    try:

        subprocess.Popen(app_name)

        print(f"[MJ] Opened {app_name}")

        return True

    except Exception:

        pass

    # ------------------------------
    # Explorer Search Fallback
    # ------------------------------

    try:

        subprocess.Popen(f'explorer.exe shell:AppsFolder')

        print(f"[MJ] Couldn't find '{app_name}'. Opened Apps list instead.")

    except Exception:

        pass

    print(f"[MJ] Unknown application: {app_name}")

    return False