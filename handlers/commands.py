"""Conversation role commands."""

from __future__ import annotations

import re

from astrbot.api import logger

from ..core.conversation import conversation_key
from ..core.roles import format_role_list, resolve_role

RESET_WORDS = {"重置", "默认", "清除", "跟随全局", "reset", "default"}
COMMAND = "声聊角色"

NO_RELAY_HINT = "没有可用的 QQ 中转群。请先在插件配置里填写中转群号，再使用该命令。"


def parse_command_arg(message: str, cmd: str = COMMAND) -> str:
    """Return whatever follows ``cmd`` in the raw command text."""
    raw = str(message or "").strip()
    match = re.match(rf"^/?{re.escape(cmd)}(?:@[^\s]+)?\s*", raw, re.IGNORECASE)
    return raw[match.end():].strip() if match else ""


def _missing_roles_hint(route) -> str:
    where = "当前群" if route.native else "中转群"
    return f"{where}没有返回可用的声聊角色。请确认 QQ 侧已开通声聊，并检查插件配置。"


async def handle_role_command(plugin, event) -> str:
    if not plugin.config.enabled:
        return "插件已停用，请先在插件配置里打开总开关。"

    context = await plugin.pipeline.command_roles(event)
    if context is None:
        return NO_RELAY_HINT

    route, roles = context
    platform_id, conversation = conversation_key(event)
    if not conversation:
        return "无法识别当前会话，请稍后再试。"
    if not roles:
        logger.info("[QQ声聊] 会话 %s/%s 没有可用的声聊角色", platform_id, conversation)
        return _missing_roles_hint(route)

    arg = parse_command_arg(event.message_str)

    if not arg:
        logger.info(
            "[QQ声聊] 会话 %s/%s 查询声聊角色，共 %d 个",
            platform_id,
            conversation,
            len(roles),
        )
        return format_role_list(roles)

    if arg in RESET_WORDS:
        plugin.state.clear_group_role(platform_id, conversation)
        logger.info(
            "[QQ声聊] 会话 %s/%s 的声聊角色已恢复跟随全局默认",
            platform_id,
            conversation,
        )
        return "已清除当前会话的单独角色配置，后续跟随全局默认角色。"

    role = resolve_role(arg, roles)
    if role is None:
        logger.info(
            "[QQ声聊] 会话 %s/%s 指定的角色 %s 不存在",
            platform_id,
            conversation,
            arg,
        )
        return f"未找到角色：{arg}\n请先用“声聊角色”查看序号。"

    plugin.state.set_group_role(platform_id, conversation, role.role_id)
    logger.info(
        "[QQ声聊] 会话 %s/%s 的声聊角色已切换为 %s",
        platform_id,
        conversation,
        role.name,
    )
    return f"已将当前会话声聊角色切换为：{role.name}\n角色 ID：{role.role_id}"
