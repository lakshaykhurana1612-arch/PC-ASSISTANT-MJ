from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class PdfPage:
    page_no_1_based: int
    text: str


def _safe_truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return text
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...<truncated>..."


def extract_pdf_page_text(pdf_path: str, page_no_1_based: int) -> PdfPage:
    """Extract text for a single page using PyMuPDF.

    page_no_1_based: human-friendly page number.
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

    if page_no_1_based < 1:
        raise ValueError("page_no_1_based must be >= 1")

    doc = fitz.open(pdf_path)
    try:
        page_count = doc.page_count
        if page_no_1_based > page_count:
            raise ValueError(f"PDF has only {page_count} pages, got {page_no_1_based}")

        page = doc.load_page(page_no_1_based - 1)
        text = page.get_text("text") or ""
        return PdfPage(page_no_1_based=page_no_1_based, text=text)
    finally:
        doc.close()


def extract_pdf_text_up_to_pages(
    pdf_path: str,
    max_pages: int = 5,
    max_total_chars: int = 25000,
) -> str:
    """Extract text from the first N pages (or fewer)."""
    try:
        import fitz  # PyMuPDF
    except Exception as e:
        raise RuntimeError(
            "PyMuPDF not installed. Add 'pymupdf' to requirements and pip install. "
            f"Import error: {e}"
        )

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(pdf_path)

    if max_pages < 1:
        max_pages = 1

    doc = fitz.open(pdf_path)
    try:
        page_count = doc.page_count
        use_pages = min(page_count, max_pages)

        chunks: list[str] = []
        total = 0
        for p in range(use_pages):
            page = doc.load_page(p)
            t = page.get_text("text") or ""
            header = f"\n\n===== Page {p+1} =====\n"
            chunk = header + t

            # account for truncation
            if max_total_chars > 0 and total + len(chunk) > max_total_chars:
                remain = max_total_chars - total
                if remain > 0:
                    chunks.append(header + _safe_truncate(t, remain - len(header)))
                break

            chunks.append(chunk)
            total += len(chunk)

        return "".join(chunks).strip()
    finally:
        doc.close()



