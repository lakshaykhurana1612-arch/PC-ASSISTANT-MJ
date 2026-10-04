import sys
import os

# 1. Project Root ka path force karo (D:\MJ)
project_root = "D:\\MJ"
if project_root not in sys.path:
    sys.path.append(project_root)

# 2. Ab safely import karo
from app.brain.groq_client import analyze_command_with_ai
from app.utils.file_manager import secure_overwrite


# ... baki ka code ...
import traceback

LAST_ERROR = None
LAST_COMMAND = None
LAST_MODULE = None

def save_error(command=None, module=None):
    global LAST_ERROR, LAST_COMMAND, LAST_MODULE

    LAST_ERROR = traceback.format_exc()
    LAST_COMMAND = command
    LAST_MODULE = module

def get_error():
    return {
        "command": LAST_COMMAND,
        "module": LAST_MODULE,
        "traceback": LAST_ERROR
    }

def clear_error():
    global LAST_ERROR, LAST_COMMAND, LAST_MODULE

    LAST_ERROR = None
    LAST_COMMAND = None
    LAST_MODULE = None

    
import traceback

def explain_error(e):
    error_text = traceback.format_exc()

    error_lower = error_text.lower()

    # Gemini overloaded
    if "503" in error_text and "unavailable" in error_lower:
        return {
            "type": "SERVER_OVERLOAD",
            "message": "Boss, mera code sahi hai. Gemini server abhi overloaded hai (503 UNAVAILABLE). Main thodi der baad dobara try karti hoon.",
            "retry": True
        }

    # API Key
    elif "api key" in error_lower or "authentication" in error_lower:
        return {
            "type": "API_KEY",
            "message": "Boss, API key me problem lag rahi hai. Ek baar .env file check kar lo.",
            "retry": False
        }

    # Internet
    elif "connection" in error_lower or "timeout" in error_lower:
        return {
            "type": "NETWORK",
            "message": "Boss, internet connection me issue lag raha hai.",
            "retry": True
        }

    # Edge TTS
    elif "NoAudioReceived" in error_text:
        return {
            "type": "TTS",
            "message": "Boss, AI ne reply de diya tha, lekin voice generate nahi ho payi.",
            "retry": True
        }

    return {
        "type": "UNKNOWN",
        "message": f"Boss, unexpected error aaya.\n\n{str(e)}",
        "retry": False
    }


from .file_manager import secure_overwrite



def report_error_to_mj(error, file_path):
    # MJ ko file content bhejo
    with open(file_path, 'r') as f:
        code_content = f.read()
    
    prompt = f"""
    FILE: {file_path}
    ERROR: {error}
    CODE: {code_content}
    
    Aap ek expert developer ho. Upar di gayi file aur error ko dekho. 
    Kya code mein `energy_threshold` ya `ambient_noise` setting mein koi galti hai? 
    Ya `recognize_google` function mein koi parameter miss ho raha hai?
    """
    # Yahan se MJ actual analysis karega
    return analyze_command_with_ai(prompt)