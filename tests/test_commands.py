"""Group role command parsing and dispatch."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from tests.astrbot_stub import install

install()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from astrbot_plugin_qq_aivoice_bridge.core.roles import Role
from astrbot_plugin_qq_aivoice_bridge.handlers.commands import (
    handle_role_command,
    parse_command_arg,
)

ROLES = [Role("lucy-voice-f36", "温柔妹妹"), Role("lucy-voice-daji", "妲己")]


class FakeState:
    def __init__(self):
        self.overrides: dict[tuple[str, str], str] = {}

    def get_group_role(self, platform_id, group_id):
        return self.overrides.get((platform_id, group_id), "")

    def set_group_role(self, platform_id, group_id, role_id):
        self.overrides[(platform_id, group_id)] = role_id

    def clear_group_role(self, platform_id, group_id):
        return self.overrides.pop((platform_id, group_id), None) is not None


class FakePipeline:
    def __init__(self, roles, native=True):
        self.roles = roles
        self.native = native

    async def native_group_roles(self, _event):
        if not self.native:
            return None
        return SimpleNamespace(platform_id="qq-main"), list(self.roles)


class FakePlugin:
    def __init__(self, roles=(), *, native=True, enabled=True):
        self.config = SimpleNamespace(enabled=enabled)
        self.state = FakeState()
        self.pipeline = FakePipeline(list(roles), native)


class FakeEvent:
    def __init__(self, message_str="声聊角色"):
        self.message_str = message_str

    def get_group_id(self):
        return "8888"


def test_parse_command_arg():
    assert parse_command_arg("声聊角色 6") == "6"
    assert parse_command_arg("/声聊角色 6") == "6"
    assert parse_command_arg("声聊角色@bot 妲己") == "妲己"
    assert parse_command_arg("声聊角色") == ""
    assert parse_command_arg("别的命令 6") == ""


def test_command_lists_roles():
    reply = asyncio.run(handle_role_command(FakePlugin(ROLES), FakeEvent()))
    assert reply == "1. 温柔妹妹\n2. 妲己"


def test_command_sets_role_by_number():
    plugin = FakePlugin(ROLES)
    reply = asyncio.run(handle_role_command(plugin, FakeEvent("声聊角色 2")))
    assert reply.startswith("已将当前群声聊角色切换为：妲己")
    assert plugin.state.overrides == {("qq-main", "8888"): "lucy-voice-daji"}


def test_command_resets_override():
    plugin = FakePlugin(ROLES)
    plugin.state.set_group_role("qq-main", "8888", "lucy-voice-daji")
    reply = asyncio.run(handle_role_command(plugin, FakeEvent("声聊角色 重置")))
    assert "跟随全局默认角色" in reply
    assert plugin.state.overrides == {}


def test_command_rejects_unknown_role():
    reply = asyncio.run(
        handle_role_command(FakePlugin(ROLES), FakeEvent("声聊角色 不存在"))
    )
    assert reply.startswith("未找到角色")


def test_command_needs_a_qq_group():
    reply = asyncio.run(
        handle_role_command(FakePlugin(ROLES, native=False), FakeEvent())
    )
    assert reply == "该命令仅支持 QQ 群聊。"


def test_command_reports_missing_roles():
    reply = asyncio.run(handle_role_command(FakePlugin(()), FakeEvent()))
    assert reply == "当前 QQ 群没有可用的声聊角色。"


def test_command_refused_when_disabled():
    reply = asyncio.run(
        handle_role_command(FakePlugin(ROLES, enabled=False), FakeEvent())
    )
    assert reply == "插件已停用，请先在插件配置里打开总开关。"
