"""Isolated, bounded PDF text extraction. No URLs or filesystem access."""

from __future__ import annotations

import io
import json
import subprocess
import sys

MAX_BYTES = 2_000_000
MAX_PAGES = 60
MAX_CHARS = 100_000


def extract_pdf(body: bytes) -> dict:
    if len(body) > MAX_BYTES or not body.startswith(b"%PDF-"):
        raise ValueError("PDF không hợp lệ hoặc vượt giới hạn 2 MB.")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pu.reporting.pdf_text"], input=body,
            capture_output=True, timeout=8, check=True,
        )
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, ValueError) as exc:
        raise ValueError("Chưa đọc được PDF trong giới hạn an toàn.") from exc


def _parse(body: bytes) -> dict:
    from pypdf import PdfReader

    if len(body) > MAX_BYTES:
        raise ValueError("PDF quá lớn.")
    reader = PdfReader(io.BytesIO(body))
    if reader.is_encrypted or not 0 < len(reader.pages) <= MAX_PAGES:
        raise ValueError("PDF mã hóa hoặc vượt giới hạn 60 trang.")
    parts, remaining = [], MAX_CHARS
    for index, page in enumerate(reader.pages, 1):
        text = f"[Trang {index}]\n{page.extract_text() or ''}\n"
        parts.append(text[:remaining])
        remaining -= len(parts[-1])
        if remaining <= 0:
            break
    text = "".join(parts)
    if not any(char.isalpha() for char in text.replace("Trang", "")):
        raise ValueError("PDF chưa có nội dung chữ có thể trích xuất.")
    return {"content": text, "page_count": len(reader.pages), "truncated": remaining <= 0}


if __name__ == "__main__":
    print(json.dumps(_parse(sys.stdin.buffer.read(MAX_BYTES + 1)), ensure_ascii=False))
