"""Normalize model prose, without decoding URLs, code, or entire JSON blobs."""

from __future__ import annotations

import re


def normalize_prose(value: object) -> str:
    text = str(value or "")
    # Protect tokens whose backslashes may be intentional.
    protected = []

    def protect(match):
        protected.append(match.group(0))
        return f"\x00PROTECTED{len(protected) - 1}\x00"

    text = re.sub(r"```[\s\S]*?```|`[^`]*`|https?://[^\s<>\\]+|[A-Za-z]:\\[^\s]+", protect, text)
    text = re.sub(r"\\{1,2}r\\{1,2}n|\\{1,2}n", "\n", text)
    text = text.replace(r"\t", "\t")
    for index, token in enumerate(protected):
        text = text.replace(f"\x00PROTECTED{index}\x00", token)
    return text.strip()
