"""Group role commands."""

from __future__ import annotations

import re

from astrbot.api import logger

from ..core.roles import format_role_list, resolve_role

RESET_WORDS = {"重置", "默认", "清除", "跟随全局", "reset", "default"}
COMMAND = "声聊角色"


def parse_command_arg(message: str, cmd: str = COMMAND) -> str:
    """Return whatever follows ``cmd`` in the raw command text."""
    raw = str(message or "").strip()
    match = re.match(rf"^/?{re.escape(cmd)}(?:@[^\s]+)?\s*", raw, re.IGNORECASE)
    return raw[match.end():].strip() if match else ""


async def handle_role_command(plugin, event) -> str:
    if not plugin.config.enabled:
        return "插件已停用，请先在插件配置里打开总开关。"

    native = await plugin.pipeline.native_group_roles(event)
    if native is None:
        return "该命令仅支持 QQ 群聊。"

    route, roles = native
    group_id = str(event.get_group_id() or "")
    if not roles:
        logger.info("[QQ声聊] 群 %s 没有可用的声聊角色", group_id)
        return "当前 QQ 群没有可用的声聊角色。"

    arg = parse_command_arg(event.message_str)

    if not arg:
        logger.info("[QQ声聊] 群 %s 查询声聊角色，共 %d 个", group_id, len(roles))
        return format_role_list(roles)

    if arg in RESET_WORDS:
        plugin.state.clear_group_role(route.platform_id, group_id)
        logger.info("[QQ声聊] 群 %s 的声聊角色已恢复跟随全局默认", group_id)
        return "已清除当前群的单独角色配置，后续跟随全局默认角色。"

    role = resolve_role(arg, roles)
    if role is None:
        logger.info("[QQ声聊] 群 %s 指定的角色 %s 不存在", group_id, arg)
        return f"未找到角色：{arg}\n请先用“声聊角色”查看序号。"

    plugin.state.set_group_role(route.platform_id, group_id, role.role_id)
    logger.info("[QQ声聊] 群 %s 的声聊角色已切换为 %s", group_id, role.name)
    return f"已将当前群声聊角色切换为：{role.name}\n角色 ID：{role.role_id}"

