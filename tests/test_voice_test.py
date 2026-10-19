"""The one-shot voice test command."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from astrbot_plugin_qq_aivoice_bridge.handlers import voice_test as voice_test_mod
from astrbot_plugin_qq_aivoice_bridge.handlers.voice_test import (
    COOLDOWN_SECONDS,
    SAMPLES,
    handle_voice_test,
)


class FakePipeline:
    def __init__(self, reply=(True, "已发送测试语音，角色：温柔妹妹")):
        self.reply = reply
        self.calls: list[str] = []

    async def speak_now(self, _event, text):
        self.calls.append(text)
        return self.reply


class FakePlugin:
    def __init__(self, *, enabled=True, reply=None):
        self.config = SimpleNamespace(enabled=enabled)
        self.pipeline = FakePipeline() if reply is None else FakePipeline(reply)


class FakeEvent:
    def __init__(self, message_str="声聊测试", group_id="10001"):
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
    voice_test_mod.reset_throttle()
    yield
    voice_test_mod.reset_throttle()


def test_refused_when_plugin_disabled():
    reply = asyncio.run(handle_voice_test(FakePlugin(enabled=False), FakeEvent()))
    assert reply == "插件已停用，请先在插件配置里打开总开关。"


def test_uses_a_sample_line_when_no_text_given():
    plugin = FakePlugin()
    asyncio.run(handle_voice_test(plugin, FakeEvent("声聊测试")))
    assert len(plugin.pipeline.calls) == 1
    assert plugin.pipeline.calls[0] in SAMPLES


def test_passes_through_the_given_text():
    plugin = FakePlugin()
    asyncio.run(handle_voice_test(plugin, FakeEvent("声聊测试 今天天气不错")))
    assert plugin.pipeline.calls == ["今天天气不错"]


def test_returns_the_pipeline_message():
    reply = asyncio.run(handle_voice_test(FakePlugin(), FakeEvent()))
    assert reply == "已发送测试语音，角色：温柔妹妹"


def test_repeats_are_throttled_per_conversation(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(voice_test_mod, "_now", lambda: now[0])

    plugin = FakePlugin()
    asyncio.run(handle_voice_test(plugin, FakeEvent()))
    now[0] += COOLDOWN_SECONDS / 2
    reply = asyncio.run(handle_voice_test(plugin, FakeEvent()))

    assert "太频繁" in reply
    assert len(plugin.pipeline.calls) == 1


def test_cooldown_expires(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(voice_test_mod, "_now", lambda: now[0])

    plugin = FakePlugin()
    asyncio.run(handle_voice_test(plugin, FakeEvent()))
    now[0] += COOLDOWN_SECONDS + 0.1
    asyncio.run(handle_voice_test(plugin, FakeEvent()))

    assert len(plugin.pipeline.calls) == 2


def test_other_conversations_are_independent(monkeypatch):
    monkeypatch.setattr(voice_test_mod, "_now", lambda: 1000.0)

    plugin = FakePlugin()
    asyncio.run(handle_voice_test(plugin, FakeEvent()))
    asyncio.run(handle_voice_test(plugin, FakeEvent(group_id="20002")))

    assert len(plugin.pipeline.calls) == 2
