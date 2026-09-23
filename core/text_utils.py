"""Text processing helpers for the QQ voice bridge."""

from __future__ import annotations

import logging
import re

try:
    from astrbot.api import logger
    from astrbot.api.message_components import Plain, Record
except ImportError:
    logger = logging.getLogger("astrbot")
    Plain = type("Plain", (), {"__init__": lambda self, text="": setattr(self, "text", text)})
    Record = type("Record", (), {})


_MD_SYMBOLS_RE = re.compile(r"\*+|`+|~~|__")
_MD_HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")


def strip_markdown(text: str) -> str:
    if not text:
        return text
    cleaned = _MD_SYMBOLS_RE.sub("", str(text))
    return _MD_HEADING_RE.sub("", cleaned).strip()


def should_skip(text: str, min_length: int, max_length: int) -> bool:
    value = str(text or "").strip()
    return not value or len(value) < min_length or len(value) > max_length


def extract_plain_text(chain) -> str:
    """Extract one continuous plain-text run from an AstrBot result chain."""
    chunks: list[str] = []
    started = False
    for component in chain or []:
        if isinstance(component, Record):
            break
        if isinstance(component, Plain) and getattr(component, "text", ""):
            chunks.append(str(component.text))
            started = True
            continue
        if started:
            break
    return "".join(chunks).strip()


def sanitize_llm_output(original: str, polished: str) -> str:
    """Reject obvious LLM runaway output and strip Markdown wrappers."""
    value = strip_markdown(str(polished or "").strip())
    if value.startswith("```"):
        value = re.sub(r"^```[a-zA-Z]*\s*", "", value)
        value = re.sub(r"\s*```\s*$", "", value).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'“”‘’":
        value = value[1:-1].strip()
    if not value:
        return ""
    if len(value) > len(str(original or "")) * 3 + 20:
        return ""
    return value

