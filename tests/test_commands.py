"""Conversation role command parsing and dispatch."""

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
    NO_RELAY_HINT,
    handle_role_command,
    parse_command_arg,
)

ROLES = [Role("lucy-voice-f36", "温柔妹妹"), Role("lucy-voice-daji", "妲己")]


class FakeState:
    def __init__(self):
        self.overrides: dict[tuple[str, str], str] = {}

    def get_group_role(self, platform_id, conversation):
        return self.overrides.get((platform_id, conversation), "")

    def set_group_role(self, platform_id, conversation, role_id):
        self.overrides[(platform_id, conversation)] = role_id

    def clear_group_role(self, platform_id, conversation):
        return self.overrides.pop((platform_id, conversation), None) is not None


class FakePipeline:
    def __init__(self, roles, route):
        self.roles = list(roles)
        self.route = route

    async def command_roles(self, _event):
        if not self.route:
            return None
        return self.route, list(self.roles)


class FakePlugin:
    def __init__(self, roles=(), *, route=None, enabled=True):
        self.config = SimpleNamespace(enabled=enabled)
        self.state = FakeState()
        if route is None:
            route = SimpleNamespace(platform_id="qq-main", group_id="7777", native=True)
        self.pipeline = FakePipeline(roles, route)


class FakeEvent:
    def __init__(self, message_str="声聊角色", group_id="8888", sender_id="10001"):
        self.message_str = message_str
        self._group_id = group_id
        self._sender_id = sender_id

    def get_platform_id(self):
        return "qq-main"

    def get_group_id(self):
        return self._group_id

    def get_sender_id(self):
        return self._sender_id


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
    assert reply.startswith("已将当前会话声聊角色切换为：妲己")
    assert plugin.state.overrides == {("qq-main", "8888"): "lucy-voice-daji"}


def test_command_sets_role_in_private_chat():
    """A private chat is keyed by sender so it cannot collide with a group id."""
    plugin = FakePlugin(ROLES, route=SimpleNamespace(platform_id="qq-main", native=False))
    event = FakeEvent("声聊角色 2", group_id="", sender_id="10001")
    asyncio.run(handle_role_command(plugin, event))
    assert plugin.state.overrides == {("qq-main", "private:10001"): "lucy-voice-daji"}


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


def test_command_without_any_qq_group():
    reply = asyncio.run(handle_role_command(FakePlugin(ROLES, route=False), FakeEvent()))
    assert reply == NO_RELAY_HINT


def test_command_refused_when_disabled():
    reply = asyncio.run(
        handle_role_command(FakePlugin(ROLES, enabled=False), FakeEvent())
    )
    assert reply == "插件已停用，请先在插件配置里打开总开关。"
