"""The voice preview command."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from astrbot_plugin_qq_aivoice_bridge.core.roles import Role
from astrbot_plugin_qq_aivoice_bridge.handlers import voice_preview as preview_mod
from astrbot_plugin_qq_aivoice_bridge.handlers.commands import NO_RELAY_HINT
from astrbot_plugin_qq_aivoice_bridge.handlers.voice_preview import (
    COOLDOWN_SECONDS,
    SAMPLES,
    handle_voice_preview,
)

ROLES = [Role("lucy-voice-f36", "温柔妹妹"), Role("lucy-voice-f34", "书香少女")]


class FakePipeline:
    def __init__(self, *, roles=None, route=True, reply=(True, "已发送试听语音")):
        self.roles = list(ROLES if roles is None else roles)
        self.route = route
        self.reply = reply
        self.calls: list[dict] = []

    async def command_roles(self, _event):
        if not self.route:
            return None
        return SimpleNamespace(platform_id="qq-main", native=False), list(self.roles)

    async def speak_now(self, _event, text, role=None, polish=True):
        self.calls.append({"text": text, "role": role, "polish": polish})
        return self.reply


class FakePlugin:
    def __init__(self, *, enabled=True, pipeline=None):
        self.config = SimpleNamespace(enabled=enabled)
        self.pipeline = pipeline or FakePipeline()


class FakeEvent:
    def __init__(self, message_str="声聊试听", group_id="10001"):
        self.message_str = message_str
        self._group_id = group_id

    def get_platform_id(self):
        return "telegram"

    def get_group_id(self):
        return self._group_id

    def get_sender_id(self):
        return "20002"


@pytest.fixture(autouse=True)
def _clean_throttle():
    preview_mod.reset_throttle()
    yield
    preview_mod.reset_throttle()


def test_refused_when_plugin_disabled():
    reply = asyncio.run(handle_voice_preview(FakePlugin(enabled=False), FakeEvent()))
    assert reply == "插件已停用，请先在插件配置里打开总开关。"


def test_without_an_argument_lists_roles_and_never_speaks():
    plugin = FakePlugin()
    reply = asyncio.run(handle_voice_preview(plugin, FakeEvent("声聊试听")))

    assert "1. 温柔妹妹" in reply
    assert "2. 书香少女" in reply
    assert "声聊试听 3" in reply
    assert plugin.pipeline.calls == []


def test_resolves_by_number():
    plugin = FakePlugin()
    asyncio.run(handle_voice_preview(plugin, FakeEvent("声聊试听 2")))

    assert len(plugin.pipeline.calls) == 1
    assert plugin.pipeline.calls[0]["role"] == ROLES[1]


def test_resolves_by_chinese_name():
    plugin = FakePlugin()
    asyncio.run(handle_voice_preview(plugin, FakeEvent("声聊试听 温柔妹妹")))

    assert plugin.pipeline.calls[0]["role"] == ROLES[0]


def test_resolves_by_role_id():
    plugin = FakePlugin()
    asyncio.run(handle_voice_preview(plugin, FakeEvent("声聊试听 lucy-voice-f34")))

    assert plugin.pipeline.calls[0]["role"] == ROLES[1]


def test_uses_a_sample_line_and_skips_polish():
    plugin = FakePlugin()
    asyncio.run(handle_voice_preview(plugin, FakeEvent("声聊试听 1")))

    call = plugin.pipeline.calls[0]
    assert call["text"] in SAMPLES
    assert call["polish"] is False


def test_extra_words_after_the_role_are_ignored():
    plugin = FakePlugin()
    asyncio.run(handle_voice_preview(plugin, FakeEvent("声聊试听 1 随便说点什么")))

    assert plugin.pipeline.calls[0]["role"] == ROLES[0]
    assert plugin.pipeline.calls[0]["text"] in SAMPLES


def test_unknown_role_is_rejected_without_speaking():
    plugin = FakePlugin()
    reply = asyncio.run(handle_voice_preview(plugin, FakeEvent("声聊试听 不存在")))

    assert reply.startswith("未找到角色：不存在")
    assert plugin.pipeline.calls == []


def test_reports_a_missing_qq_group():
    reply = asyncio.run(
        handle_voice_preview(FakePlugin(pipeline=FakePipeline(route=False)), FakeEvent())
    )
    assert reply == NO_RELAY_HINT


def test_returns_the_pipeline_message():
    plugin = FakePlugin(pipeline=FakePipeline(reply=(True, "已发送试听语音，角色：温柔妹妹")))
    reply = asyncio.run(handle_voice_preview(plugin, FakeEvent("声聊试听 1")))
    assert reply == "已发送试听语音，角色：温柔妹妹"


def test_repeats_are_throttled_per_conversation(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(preview_mod, "_now", lambda: now[0])

    plugin = FakePlugin()
    asyncio.run(handle_voice_preview(plugin, FakeEvent("声聊试听 1")))
    now[0] += COOLDOWN_SECONDS / 2
    reply = asyncio.run(handle_voice_preview(plugin, FakeEvent("声聊试听 1")))

    assert "太频繁" in reply
    assert len(plugin.pipeline.calls) == 1


def test_cooldown_expires(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(preview_mod, "_now", lambda: now[0])

    plugin = FakePlugin()
    asyncio.run(handle_voice_preview(plugin, FakeEvent("声聊试听 1")))
    now[0] += COOLDOWN_SECONDS + 0.1
    asyncio.run(handle_voice_preview(plugin, FakeEvent("声聊试听 1")))

    assert len(plugin.pipeline.calls) == 2


def test_listing_is_not_throttled(monkeypatch):
    monkeypatch.setattr(preview_mod, "_now", lambda: 1000.0)

    plugin = FakePlugin()
    asyncio.run(handle_voice_preview(plugin, FakeEvent("声聊试听 1")))
    reply = asyncio.run(handle_voice_preview(plugin, FakeEvent("声聊试听")))

    assert "1. 温柔妹妹" in reply


def test_other_conversations_are_independent(monkeypatch):
    monkeypatch.setattr(preview_mod, "_now", lambda: 1000.0)

    plugin = FakePlugin()
    asyncio.run(handle_voice_preview(plugin, FakeEvent("声聊试听 1")))
    asyncio.run(handle_voice_preview(plugin, FakeEvent("声聊试听 1", group_id="20002")))

    assert len(plugin.pipeline.calls) == 2
