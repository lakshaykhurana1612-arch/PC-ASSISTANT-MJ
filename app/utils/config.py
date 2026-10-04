# config.py
import os

PRIMARY_API_KEY = os.getenv("GEMINI_API_KEY")
BACKUP_API_KEY = os.getenv("GEMINI_API_KEY_2")

# Model names
PRIMARY_MODEL = "gemini-2.5-flash"
BACKUP_MODEL = "gemini-2.5-flash"