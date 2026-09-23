"""Pure segmentation planning for voice delivery."""

from __future__ import annotations

import random
import re
from collections.abc import Callable
from dataclasses import dataclass

SEGMENT_PATTERNS = {
    "sentence": r"[。！？!?]",
    "paragraph": r"\n{2,}",
    "comma": r"[，,；;]",
    "mixed": r"[。！？!?\n]",
}

_BLANK_RE = re.compile(r"^(?:[-=*_~—·.>\s]|#)+$")

BUNDLED = "bundled"
TEXT_FIRST = "text_first"
VOICE_ONLY = "voice_only"
TEXT_FALLBACK = "text_fallback"
DROP = "drop"


@dataclass
class SegmentPlan:
    text: str
    short: bool
    want_voice: bool
    blank: bool = False


def split_text(text: str, pattern: str, max_count: int) -> list[str]:
    regex = SEGMENT_PATTERNS.get(pattern, SEGMENT_PATTERNS["sentence"])
    parts = [part.strip() for part in re.split(regex, text) if part.strip()]
    if max_count > 0 and len(parts) > max_count:
        parts = parts[: max_count - 1] + ["".join(parts[max_count - 1 :])]
    return parts


def plan_segments(
    segments: list[str],
    *,
    min_length: int,
    probability: float,
    rng: Callable[[], float] = random.random,
) -> list[SegmentPlan]:
    plans: list[SegmentPlan] = []
    for segment in segments:
        if not segment or _BLANK_RE.match(segment):
            plans.append(SegmentPlan(segment, False, False, True))
        elif len(segment) < min_length:
            plans.append(SegmentPlan(segment, True, False))
        else:
            plans.append(SegmentPlan(segment, False, rng() < probability))
    return plans


def resolve_delivery(
    *,
    short: bool,
    want_voice: bool,
    text_enabled: bool,
    text_async: bool,
    fallback_enabled: bool,
    blank: bool = False,
) -> str:
    if blank:
        return DROP
    if short:
        # A segment below the minimum length can never be spoken, so it always
        # goes out as text; otherwise its wording vanishes from the reply.
        return TEXT_FALLBACK
    if not want_voice:
        return TEXT_FALLBACK if fallback_enabled else DROP
    if not text_enabled:
        return VOICE_ONLY
    return TEXT_FIRST if text_async else BUNDLED

