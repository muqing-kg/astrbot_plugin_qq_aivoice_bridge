"""One-shot voice test command."""

from __future__ import annotations

import random
import time

from astrbot.api import logger

from ..core.conversation import conversation_key
from .commands import parse_command_arg

COMMAND = "声聊测试"

# Stand-in lines used when the command is sent without text, so a test never
# costs an extra LLM call just to invent a sentence.
SAMPLES: tuple[str, ...] = (
    "这是一条声聊测试语音，听到就说明链路已经通了。",
    "用这句话试一下声聊，听听声音顺不顺耳。",
    "声聊已经接通，随时都可以开口说话。",
)

# A test is cheap to repeat and easy to spam, so one conversation is throttled.
COOLDOWN_SECONDS = 3.0
COOLDOWN_MAX_ENTRIES = 256

_last_used: dict[tuple[str, str], float] = {}


def _now() -> float:
    return time.monotonic()


def _throttled(key: tuple[str, str], now: float) -> bool:
    last = _last_used.get(key)
    if last is not None and now - last < COOLDOWN_SECONDS:
        return True
    if len(_last_used) >= COOLDOWN_MAX_ENTRIES:
        for stale in [
            item for item, stamp in _last_used.items() if now - stamp >= COOLDOWN_SECONDS
        ]:
            _last_used.pop(stale, None)
    _last_used[key] = now
    return False


def reset_throttle() -> None:
    """Clear the cooldown table; used by tests to keep runs independent."""
    _last_used.clear()


async def handle_voice_test(plugin, event) -> str:
    if not plugin.config.enabled:
        return "插件已停用，请先在插件配置里打开总开关。"

    if _throttled(conversation_key(event), _now()):
        return f"测试太频繁了，{COOLDOWN_SECONDS:.0f} 秒后再试。"

    text = parse_command_arg(event.message_str, COMMAND)
    if not text:
        text = random.choice(SAMPLES)

    ok, message = await plugin.pipeline.speak_now(event, text)
    logger.info("[QQ声聊] 测试语音%s：%s", "已发送" if ok else "失败", message)
    return message
