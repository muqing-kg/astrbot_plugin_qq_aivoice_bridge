"""Voice preview command: hear any role without changing the configuration."""

from __future__ import annotations

import random
import time

from astrbot.api import logger

from ..core.conversation import conversation_key
from ..core.roles import format_role_list, resolve_role
from .commands import NO_RELAY_HINT, parse_command_arg

COMMAND = "声聊试听"

# Written to be heard rather than read, so a preview never costs an LLM call.
SAMPLES: tuple[str, ...] = (
    "这句话是用来试听的，听听这个声音合不合心意，喜欢的话就把角色定下来。",
    "声音已经换成现在试听的这一个了，觉得顺耳就留着，不合意就再换一个。",
    "现在读的是试听台词，语速和语气都在这里了，听完再决定要不要用。",
    "这一句专门用来听音色，短一点，方便和别的角色对着比。",
    "试听就到这里，觉得合适的话，在群里发一声就能把它设成当前会话的角色。",
)

# Auditioning is cheap to repeat and easy to spam, so one conversation is
# throttled.
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


async def handle_voice_preview(plugin, event) -> str:
    if not plugin.config.enabled:
        return "插件已停用，请先在插件配置里打开总开关。"

    context = await plugin.pipeline.command_roles(event)
    if context is None:
        return NO_RELAY_HINT

    _, roles = context
    arg = parse_command_arg(event.message_str, COMMAND)

    if not arg:
        return (
            f"{format_role_list(roles)}\n\n"
            f"发送「{COMMAND} 序号」即可试听，例如：{COMMAND} 3"
        )

    token = arg.split()[0]
    role = resolve_role(token, roles)
    if role is None:
        logger.info("[QQ声聊] 试听请求的角色 %s 不存在", token)
        return f"未找到角色：{token}\n发送「{COMMAND}」可以查看序号。"

    if _throttled(conversation_key(event), _now()):
        return f"试听太频繁了，{COOLDOWN_SECONDS:.0f} 秒后再试。"

    ok, message = await plugin.pipeline.speak_now(
        event,
        random.choice(SAMPLES),
        role=role,
        polish=False,
    )
    logger.info(
        "[QQ声聊] 试听角色 %s（%s）%s：%s",
        role.name,
        role.role_id,
        "成功" if ok else "失败",
        message,
    )
    return message
