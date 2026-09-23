"""Flat configuration facade for nested AstrBot plugin config."""

from __future__ import annotations

from typing import Any, ClassVar

DEFAULT_POLISH_PROMPT = (
    "你是一个中文口语化改写助手。把下面的机器人回复改写成日常聊天时会说出口的话，"
    "保持原意、事实、数字和专有名词不变，可以调整语序，但不要新增或删减信息。"
    "只输出改写后的纯文本，不要解释。\n\n原文：{text}"
)

# The role a group follows when none is configured. Kept as a literal so that
# reordering ``BUILTIN_ROLES`` cannot silently change the default.
DEFAULT_ROLE_ID = "lucy-voice-f36"


class ConfigManager:
    _DEFAULTS: ClassVar[dict[str, Any]] = {
        "enabled": True,
        "qq_platforms": [],
        "relay_group": "",
        "default_role": DEFAULT_ROLE_ID,
        "audio_format": "wav",
        "probability": 0.1,
        "auto_tts": True,
        "send_text_with_tts": False,
        "send_text_async": False,
        "min_text_length": 5,
        "max_text_length": 500,
        "enable_segmentation": False,
        "segment_pattern": "sentence",
        "segment_max_count": 10,
        "segment_voice_probability": 1.0,
        "segment_text_fallback": True,
        "enable_voice_polish": True,
        "display_polished_text": False,
        "polish_llm_provider": "",
        "polish_prompt": DEFAULT_POLISH_PROMPT,
        "timeout": 30,
        "max_retries": 1,
        "max_concurrency": 2,
        "ffmpeg_path": "ffmpeg",
    }

    def __init__(self, raw: dict | None):
        self._raw = raw or {}
        self._flat: dict[str, Any] = {}
        self._flatten(self._raw)
        for key, value in self._DEFAULTS.items():
            self._flat.setdefault(key, self._copy(value))

    @staticmethod
    def _copy(value):
        if isinstance(value, list):
            return list(value)
        if isinstance(value, dict):
            return dict(value)
        return value

    def _flatten(self, src: dict) -> None:
        for key, value in src.items():
            if isinstance(value, dict):
                self._flatten(value)
                continue
            self._flat[key] = value

    def get(self, key: str, default=None):
        return self._flat.get(key, default)

    @property
    def enabled(self) -> bool:
        return bool(self._flat.get("enabled", True))

    @property
    def qq_platforms(self) -> list[str]:
        raw = self._flat.get("qq_platforms", [])
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            return []
        return [str(item).strip() for item in raw if str(item or "").strip()]

    @property
    def relay_group(self) -> str:
        return str(self._flat.get("relay_group", "") or "").strip()

    @property
    def default_role(self) -> str:
        value = str(self._flat.get("default_role", "") or "").strip()
        if value:
            return value
        return DEFAULT_ROLE_ID

    @property
    def audio_format(self) -> str:
        value = str(self._flat.get("audio_format", "wav") or "wav").lower()
        return value if value in {"silk", "wav", "mp3"} else "wav"

    @property
    def probability(self) -> float:
        return self._float("probability", 0.1, 0.0, 1.0)

    @property
    def auto_tts(self) -> bool:
        return bool(self._flat.get("auto_tts", True))

    @property
    def send_text_with_tts(self) -> bool:
        return bool(self._flat.get("send_text_with_tts", False))

    @property
    def send_text_async(self) -> bool:
        return bool(self._flat.get("send_text_async", False))

    @property
    def min_text_length(self) -> int:
        return max(0, self._int("min_text_length", 5))

    @property
    def max_text_length(self) -> int:
        return max(1, self._int("max_text_length", 500))

    @property
    def enable_segmentation(self) -> bool:
        return bool(self._flat.get("enable_segmentation", False))

    @property
    def segment_pattern(self) -> str:
        value = str(self._flat.get("segment_pattern", "sentence") or "sentence")
        return value if value in {"sentence", "paragraph", "comma", "mixed"} else "sentence"

    @property
    def segment_max_count(self) -> int:
        return max(0, self._int("segment_max_count", 10))

    @property
    def segment_voice_probability(self) -> float:
        return self._float("segment_voice_probability", 1.0, 0.0, 1.0)

    @property
    def segment_text_fallback(self) -> bool:
        return bool(self._flat.get("segment_text_fallback", True))

    @property
    def enable_voice_polish(self) -> bool:
        return bool(self._flat.get("enable_voice_polish", True))

    @property
    def display_polished_text(self) -> bool:
        return bool(self._flat.get("display_polished_text", False))

    @property
    def polish_llm_provider(self) -> str:
        return str(self._flat.get("polish_llm_provider", "") or "").strip()

    @property
    def polish_prompt(self) -> str:
        return str(self._flat.get("polish_prompt", "") or "").strip()

    @property
    def timeout(self) -> int:
        return max(1, self._int("timeout", 30))

    @property
    def max_retries(self) -> int:
        return max(0, self._int("max_retries", 1))

    @property
    def max_concurrency(self) -> int:
        return max(1, self._int("max_concurrency", 2))

    @property
    def ffmpeg_path(self) -> str:
        return str(self._flat.get("ffmpeg_path", "ffmpeg") or "ffmpeg").strip()

    def _int(self, key: str, default: int) -> int:
        try:
            return int(self._flat.get(key, default))
        except (TypeError, ValueError):
            return default

    def _float(self, key: str, default: float, low: float, high: float) -> float:
        try:
            value = float(self._flat.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(low, min(high, value))
