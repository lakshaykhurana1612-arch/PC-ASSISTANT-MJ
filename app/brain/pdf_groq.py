from __future__ import annotations

import os
import datetime
import traceback

from dotenv import load_dotenv
from groq import Groq

from app.utils.file_manager import find_file, read_file

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")


def _get_groq_client() -> Groq:
    if not GROQ_API_KEY:
        raise Exception("Groq API Key not found (GROQ_API_KEY).")
    return Groq(api_key=GROQ_API_KEY)


def ask_groq_about_pdf(
    user_request: str,
    pdf_text_chunk: str,
    *,
    page_hint: int | None = None,
) -> str:
    """Send extracted PDF/file text to Groq and get an answer."""

    now = datetime.datetime.now().strftime("%A, %d %B %Y, %I:%M %p")

    system_prompt = """
You are MJ, a helpful assistant.

Answer ONLY using the provided file content.

If the answer is not present in the file, reply:

"I couldn't find that information in the provided file."

Never make up information.
Keep answers accurate and concise.
""".strip()

    if page_hint is not None:
        page_context = f"Relevant page: {page_hint}"
    else:
        page_context = "Whole file"

    user_prompt = (
        f"{page_context}\n"
        f"Current Date & Time: {now}\n\n"
        f"User Request:\n{user_request}\n\n"
        f"========== FILE CONTENT =========\n"
        f"{pdf_text_chunk}\n"
        f"========== END =========\n\n"
        f"Answer only from the above content."
    )

    groq_client = _get_groq_client()

    try:
        response = groq_client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            temperature=0.2,
        )

        return response.choices[0].message.content.strip()

    except Exception:
        traceback.print_exc()
        return "CHAT: Boss, Groq se file analysis nahi ho paya."


def analyze_file(filename: str, user_request: str) -> str:
    """Find a file by name, read it and ask Groq."""

    path = find_file(filename)
    if not path:
        return f"CHAT: Boss, '{filename}' naam ki file nahi mili."

    try:
        text = read_file(path)
    except Exception:
        print(traceback.format_exc())
        return "CHAT: Boss, file read nahi ho payi.\n\n" + traceback.format_exc()

    if not text or not text.strip():
        return "CHAT: Boss, file me readable content nahi mila."

    return ask_groq_about_pdf(
        user_request=user_request,
        pdf_text_chunk=text,
    )

