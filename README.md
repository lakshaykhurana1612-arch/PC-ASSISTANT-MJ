# MJ Assistant

MJ is a Windows desktop assistant written in Python. It combines voice input and speech output with Gemini/Groq-powered command interpretation, local file search, browser automation, and desktop actions.

## Features

- Typed commands and microphone-based voice input
- Gemini primary/backup and Groq fallback for command interpretation
- Text-to-speech responses and wake-word support
- Local file search and selected browser, WhatsApp, and desktop automations
- Modular planner, memory, and provider components

Some actions interact with local files, applications, and the operating system. Review commands before enabling or using automation features.

## Requirements

- Windows
- Python 3.10 or newer
- A microphone for voice input
- API credentials for the AI providers you plan to use

Some dependencies, especially audio packages, may require platform-specific setup.

## Setup

Open PowerShell in the project directory and run:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and set the credentials you use:

| Variable | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | Primary Gemini key |
| `GEMINI_API_KEY_2` | Optional backup Gemini key |
| `GROQ_API_KEY` | Groq fallback key |
| `MJ_PASSWORD` | Password required by protected file-write actions |
| `DEEPGRAM_API_KEY` | Reserved/optional provider setting |

Keep `.env` private. Never paste API keys into source files or commit them to Git.

## Run

With the virtual environment active and `.env` configured:

```powershell
python main.py
```

The app may request microphone access and can launch or control local applications as part of automation features.

## Project Layout

- `main.py`: application entry point and command orchestration
- `app/brain/`: LLM clients, intent routing, prompts, and planning
- `app/utils/`: voice, file, browser, and automation helpers
- `app/voice_engine/`: speech capture, recognition, and playback components
- `docs/ARCHITECTURE.md`: architecture and command execution details

## Security

Local credentials and personal documents are excluded by `.gitignore`. Before publishing, verify that the repository contains no secrets or personal files. If a key has been exposed, revoke it with its provider and replace it; deleting it from a file does not invalidate it.
