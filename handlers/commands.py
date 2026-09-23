"""Group role commands."""

from __future__ import annotations

from ..core.roles import format_role_list, resolve_role

RESET_WORDS = {"重置", "默认", "清除", "跟随全局", "reset", "default"}


async def handle_role_command(plugin, event) -> str:
    native = await plugin.pipeline.native_group_roles(event)
    if native is None:
        return "该命令仅支持 QQ 群聊。"

    route, roles = native
    if not roles:
        return "当前 QQ 群没有可用的声聊角色。"

    arg = plugin._parse_cmd(event, "声聊角色").strip()
    group_id = str(event.get_group_id() or "")

    if not arg:
        return format_role_list(roles)

    if arg in RESET_WORDS:
        plugin.state.clear_group_role(route.platform_id, group_id)
        return "已清除当前群的单独角色配置，后续跟随全局默认角色。"

    role = resolve_role(arg, roles)
    if role is None:
        return f"未找到角色：{arg}\n请先用“声聊角色”查看序号。"

    plugin.state.set_group_role(route.platform_id, group_id, role.role_id)
    return f"已将当前群声聊角色切换为：{role.name}\n角色 ID：{role.role_id}"

