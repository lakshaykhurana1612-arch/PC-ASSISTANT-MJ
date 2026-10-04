import os
import shutil


skip_folders = {

    "$recycle.bin",
    "system volume information",
    "windows",
    "program files",
    "program files (x86)",
    "appdata"
}


def get_drives():
    drives = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        drive = f"{letter}:\\"
        if os.path.exists(drive):
            drives.append(drive)
    return drives


import os
import re


import os
import re

skip_files = {
    "hiberfil.sys",
    "pagefile.sys",
    "swapfile.sys",
}


def find_file(query):
    """
    Search complete PC for a file.

    Features:
    - Ignores extension in query
    - Case insensitive
    - Supports _, -, .
    - Returns best matching file
    - Ignores Windows system files/folders
    """

    if not query:
        return None

    # Remove extension if user typed one
    query = os.path.splitext(query)[0]

    # Normalize query
    query = re.sub(r"[_.\-]+", " ", query.lower())
    query_words = [w for w in query.split() if w]

    if not query_words:
        return None

    best_match = None
    best_score = 0

    for drive in get_drives():

        for root, dirs, files in os.walk(drive):

            # Skip system folders
            dirs[:] = [
                d for d in dirs
                if d.lower() not in skip_folders
            ]

            for file in files:

                # Skip Windows system files
                if file.lower() in skip_files:
                    continue

                filename = os.path.splitext(file)[0].lower()
                normalized = re.sub(r"[_.\-]+", " ", filename)

                score = 0

                for word in query_words:
                    if word in normalized:
                        score += 1

                # Ignore weak matches
                if score == 0:
                    continue

                # Perfect match
                if score == len(query_words):
                    return os.path.join(root, file)

                # Better partial match
                if score > best_score:
                    best_score = score
                    best_match = os.path.join(root, file)

    # Require at least half the words to match
    min_required = max(1, (len(query_words) + 1) // 2)

    if best_score >= min_required:
        return best_match

    return None

def open_file(path):
    """Open a file with its associated Windows app.

    Important: avoid popping up an extra console window. If os.startfile fails,
    use a no-window subprocess fallback.
    """

    try:
        os.startfile(path)
        # Keep this silent to avoid extra console noise in "read" commands.
        # print(f"[MJ] Opened {path}")
        return True

    except Exception:
        # Fallback: launch via subprocess without creating a new console window.
        try:
            import subprocess
            import sys

            # Use shell=True so Windows handles file associations.
            creationflags = 0
            if sys.platform.startswith("win"):
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            subprocess.Popen(
                [path],
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            return True
        except Exception:
            return False


def move_file(source_path, dest_folder):
    """
    Move a file from source_path to dest_folder.
    Creates the destination folder if it doesn't exist.
    Returns (success: bool, message: str).
    """
    if not os.path.exists(source_path):
        return False, f"File not found: {source_path}"

    if not os.path.isfile(source_path):
        return False, f"Not a file: {source_path}"

    try:
        os.makedirs(dest_folder, exist_ok=True)
        filename = os.path.basename(source_path)
        dest_path = os.path.join(dest_folder, filename)

        # If destination already has a file with the same name, add a number suffix
        if os.path.exists(dest_path):
            name, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(os.path.join(dest_folder, f"{name}_{counter}{ext}")):
                counter += 1
            dest_path = os.path.join(dest_folder, f"{name}_{counter}{ext}")

        shutil.move(source_path, dest_path)
        return True, f"Moved to {dest_path}"

    except Exception as e:
        return False, f"Move failed: {e}"


def delete_file(file_path):
    """
    Delete a file permanently (not to Recycle Bin).
    Returns (success: bool, message: str).
    """
    if not os.path.exists(file_path):
        return False, f"File not found: {file_path}"

    if not os.path.isfile(file_path):
        return False, f"Not a file: {file_path}"

    try:
        os.remove(file_path)
        return True, f"Deleted: {file_path}"
    except Exception as e:
        return False, f"Delete failed: {e}"

    
# Set MJ_PASSWORD in your .env file before using protected writes.
PASSWORD = os.getenv("MJ_PASSWORD")

def secure_overwrite(file_path, new_content, password_input):
    if not PASSWORD or password_input != PASSWORD:
        return "Error: Authentication Failed. Cannot overwrite file."
    
    try:
        with open(file_path, 'w') as f:
            f.write(new_content)
        return f"Success: {file_path} has been updated."
    except Exception as e:
        return f"System Error: {str(e)}"

import os

def read_text_file(file_path: str, max_chars: int = 20000) -> str:
    """Safely read a text file and truncate to max_chars.

    - Tries utf-8 first, then falls back to latin-1.
    - Returns a string (never raises for decode errors).
    """
    if not file_path or not os.path.exists(file_path):
        raise FileNotFoundError(file_path)

    if not os.path.isfile(file_path):
        raise IsADirectoryError(file_path)

    # Read as bytes first to avoid decode crashes on weird encodings.
    with open(file_path, "rb") as f:
        raw = f.read(max_chars + 1024)

    # Heuristic decode
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = raw.decode(enc, errors="strict")
            break
        except Exception:
            text = None

    if text is None:
        # Last resort: replace errors
        text = raw.decode("utf-8", errors="replace")

    text = text.replace("\x00", "")
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars] + "\n...<truncated>..."
    return text


def apply_patch(file_path, code_patch):
    """
    Ye function MJ dwara generate kiya gaya fix apply karega.
    """
    password = input("🔒 Enter Password to overwrite: ")
    
    if PASSWORD and password == PASSWORD:
        with open(file_path, 'w') as f:
            f.write(code_patch)
        return True
    else:
        print("❌ Password incorrect!")
        return False

def read_pdf(file_path, max_chars=25000):
    import fitz

    doc = fitz.open(file_path)

    text = ""

    for page in doc:
        text += page.get_text("text")

        if len(text) >= max_chars:
            break

    doc.close()

    return text[:max_chars]


def read_docx(file_path):

    from docx import Document

    doc = Document(file_path)

    return "\n".join(p.text for p in doc.paragraphs)


def read_file(path):

    ext = os.path.splitext(path)[1].lower()

    if ext == ".pdf":
        return read_pdf(path)

    elif ext == ".docx":
        return read_docx(path)

    elif ext in (
        ".txt",
        ".py",
        ".json",
        ".csv",
        ".md",
        ".html",
        ".css",
        ".js",
        ".xml",
        ".ini",
        ".yaml",
        ".yml"
    ):
        return read_text_file(path)

    else:
        raise Exception(f"Unsupported file type: {ext}")
    
from dataclasses import dataclass

@dataclass
class PdfPage:
    page_no_1_based: int
    text: str

def find_best_pages_by_keyword(
    pdf_path: str,
    keyword: str,
    max_pages_to_scan: int = 30,
    max_hits: int = 5,
) -> list[PdfPage]:
    """Very lightweight keyword search across first N pages.

    Returns up to max_hits pages with the most occurrences.
    """
    try:
        import fitz  # PyMuPDF
    except Exception as e:
        raise RuntimeError(
            "PyMuPDF not installed. Add 'pymupdf' to requirements and pip install. "
            f"Import error: {e}"
        )

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(pdf_path)

    keyword = (keyword or "").strip().lower()
    if not keyword:
        return []

    doc = fitz.open(pdf_path)
    try:
        page_count = doc.page_count
        use_pages = min(page_count, max_pages_to_scan)

        scored: list[tuple[int, int, str]] = []  # (score, page_no_1_based, snippet)

        for p in range(use_pages):
            page = doc.load_page(p)
            text = page.get_text("text") or ""
            lt = text.lower()
            idx = lt.find(keyword)
            if idx == -1:
                continue

            # score by number of occurrences (cap for perf)
            score = lt.count(keyword)

            # snippet around first hit
            start = max(0, idx - 300)
            end = min(len(text), idx + 700)
            snippet = text[start:end]
            scored.append((score, p + 1, snippet))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:max_hits]
        return [PdfPage(page_no_1_based=pn, text=snip) for _, pn, snip in top]
    finally:
        doc.close()

