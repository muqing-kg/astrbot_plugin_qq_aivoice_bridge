import asyncio
from types import SimpleNamespace

from core.qq_voice import QQVoiceClient, platform_meta


class FakeConfig:
    def __init__(self, qq_platforms, relay_group="10086", max_retries=1, timeout=5):
        self.qq_platforms = qq_platforms
        self.relay_group = relay_group
        self.max_retries = max_retries
        self.timeout = timeout


class FakePlatformManager:
    def __init__(self, adapters):
        self.adapters = adapters

    def get_insts(self):
        return self.adapters


class FakeContext:
    def __init__(self, adapters):
        self.platform_manager = FakePlatformManager(adapters)


class FakeEvent:
    def __init__(self, platform_id, platform_name, group_id="", bot=None):
        self.platform_id = platform_id
        self.platform_name = platform_name
        self.group_id = group_id
        self.bot = bot

    def get_platform_id(self):
        return self.platform_id

    def get_platform_name(self):
        return self.platform_name

    def get_group_id(self):
        return self.group_id


def adapter(platform_id):
    meta = SimpleNamespace(name="aiocqhttp", id=platform_id)
    return SimpleNamespace(meta=lambda: meta, bot=f"bot:{platform_id}")


def test_empty_selection_uses_current_qq_group():
    qq_adapter = adapter("qq-main")
    client = QQVoiceClient(FakeContext([qq_adapter]), FakeConfig([]))
    route = client.resolve_route(
        FakeEvent("qq-main", "aiocqhttp", "group-1", qq_adapter.bot)
    )
    assert route is not None
    assert route.native is True
    assert route.group_id == "group-1"
    assert route.bot == qq_adapter.bot


def test_qq_private_uses_relay_group():
    qq_adapter = adapter("qq-main")
    client = QQVoiceClient(FakeContext([qq_adapter]), FakeConfig([]))
    route = client.resolve_route(
        FakeEvent("qq-main", "aiocqhttp", "", qq_adapter.bot)
    )
    assert route is not None
    assert route.native is False
    assert route.group_id == "10086"


def test_non_qq_platform_uses_selected_qq_adapter():
    qq_adapter = adapter("qq-main")
    client = QQVoiceClient(
        FakeContext([qq_adapter]),
        FakeConfig(["qq-main"]),
    )
    route = client.resolve_route(
        FakeEvent("wechat", "aiocqhttp", "wechat-group", "wechat-bot")
    )
    assert route is not None
    assert route.native is False
    assert route.bot == qq_adapter.bot
    assert route.group_id == "10086"


def test_without_relay_group_route_is_none():
    qq_adapter = adapter("qq-main")
    client = QQVoiceClient(FakeContext([qq_adapter]), FakeConfig([], relay_group=""))
    assert client.resolve_route(FakeEvent("wechat", "telegram", "group")) is None


def test_platform_meta_prefers_meta_method_then_attribute():
    meta = SimpleNamespace(name="aiocqhttp", id="qq-main")
    assert platform_meta(SimpleNamespace(meta=lambda: meta)) is meta
    assert platform_meta(SimpleNamespace(metadata=meta)) is meta
    assert platform_meta(SimpleNamespace()) is None


def test_with_retries_retries_then_succeeds():
    client = QQVoiceClient(FakeContext([]), FakeConfig([], max_retries=2))
    calls = {"n": 0}

    async def action():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("boom")
        return "ok"

    assert asyncio.run(client._with_retries("测试", action)) == "ok"
    assert calls["n"] == 3


def test_with_retries_gives_up_after_budget():
    client = QQVoiceClient(FakeContext([]), FakeConfig([], max_retries=1))
    calls = {"n": 0}

    async def action():
        calls["n"] += 1
        raise RuntimeError("always")

    try:
        asyncio.run(client._with_retries("测试", action))
    except RuntimeError as exc:
        assert "always" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
    assert calls["n"] == 2


def test_with_retries_applies_timeout():
    client = QQVoiceClient(FakeContext([]), FakeConfig([], max_retries=0, timeout=0.05))

    async def slow():
        await asyncio.sleep(1)
        return "late"

    try:
        asyncio.run(client._with_retries("测试", slow))
    except TimeoutError:
        pass
    else:
        raise AssertionError("expected TimeoutError")
