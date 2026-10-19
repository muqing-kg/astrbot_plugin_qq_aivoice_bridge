"""WebUI backend for per-conversation role overrides."""

from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace

from core.page_api import PLUGIN_NAME, RolePageAPI
from core.roles import BUILTIN_ROLES, Role


class FakeState:
    def __init__(self, entries=(), cached=None):
        self.entries: list[tuple[str, str, str]] = list(entries)
        self.cached = cached or {}

    def list_group_roles(self):
        return list(self.entries)

    def get_cached_roles(self, platform_id, group_id):
        return self.cached.get((platform_id, group_id), [])

    def set_group_role(self, platform_id, conversation, role_id):
        self.entries = [
            item
            for item in self.entries
            if item[:2] != (platform_id, conversation)
        ]
        self.entries.append((platform_id, conversation, role_id))

    def clear_group_role(self, platform_id, conversation):
        before = len(self.entries)
        self.entries = [
            item
            for item in self.entries
            if item[:2] != (platform_id, conversation)
        ]
        return len(self.entries) != before


class FakeQQ:
    def __init__(self, relay=None, names=None):
        self.relay = relay
        self.names = names or {}

    def relay_route(self):
        return self.relay

    async def group_display_name(self, platform_id, group_id):
        return self.names.get((platform_id, group_id), "")


class FakeContext:
    def __init__(self):
        self.routes: list[tuple] = []

    def register_web_api(self, route, handler, methods, desc):
        self.routes.append((route, handler, tuple(methods), desc))


class FakePlugin:
    def __init__(self, *, state=None, qq=None, default_role=""):
        self.state = state or FakeState()
        self.qq = qq or FakeQQ()
        self.config = SimpleNamespace(default_role=default_role)
        self.context = FakeContext()


class FakeRequest:
    def __init__(self, payload=None):
        self.payload = payload or {}

    async def json(self, default=None):
        return self.payload or default or {}


class AwaitablePropertyRequest:
    """Older Quart-style request: ``json`` is an awaitable property."""

    def __init__(self, payload=None):
        self.payload = payload or {}

    @property
    def json(self):
        async def _body():
            return self.payload

        return _body()


class DictPropertyRequest:
    """Some builds expose the parsed body directly as a property."""

    def __init__(self, payload=None):
        self.payload = payload or {}

    @property
    def json(self):
        return self.payload


def _api(plugin, payload=None):
    api = RolePageAPI(plugin)
    api._json = lambda data: data
    api._error = lambda message: {"error": message}
    api._request = FakeRequest(payload)
    return api


def test_register_degrades_without_page_api():
    """Older AstrBot builds have no astrbot.api.web; registering must not raise."""
    plugin = FakePlugin()
    RolePageAPI(plugin).register()
    assert plugin.context.routes == []


def test_register_mounts_three_routes(monkeypatch):
    web = types.ModuleType("astrbot.api.web")
    web.json_response = lambda data: data
    web.error_response = lambda message: {"error": message}
    web.request = FakeRequest()
    monkeypatch.setitem(sys.modules, "astrbot.api.web", web)

    plugin = FakePlugin()
    RolePageAPI(plugin).register()

    routes = [route for route, *_ in plugin.context.routes]
    assert routes == [
        f"/{PLUGIN_NAME}/page/roles",
        f"/{PLUGIN_NAME}/page/roles/set",
        f"/{PLUGIN_NAME}/page/roles/delete",
    ]


def test_list_roles_falls_back_to_the_builtin_catalog():
    plugin = FakePlugin()
    data = asyncio.run(_api(plugin).list_roles())

    assert data["catalog_source"] == "builtin"
    assert len(data["catalog"]) == len(BUILTIN_ROLES)
    assert data["entries"] == []


def test_list_roles_prefers_the_live_catalog():
    relay = SimpleNamespace(platform_id="qq-main", group_id="7777")
    live = [Role("custom-1", "自定义角色")]
    plugin = FakePlugin(
        qq=FakeQQ(relay=relay),
        state=FakeState(cached={("qq-main", "7777"): live}),
    )
    data = asyncio.run(_api(plugin).list_roles())

    assert data["catalog_source"] == "live"
    assert data["catalog"] == [{"role_id": "custom-1", "name": "自定义角色"}]


def test_list_roles_resolves_names_and_marks_stale_ids():
    plugin = FakePlugin(
        state=FakeState(
            entries=[
                ("qq-main", "8888", "lucy-voice-daji"),
                ("qq-main", "9999", "removed-role"),
                ("telegram", "private:10001", "lucy-voice-f36"),
            ]
        ),
        qq=FakeQQ(names={("qq-main", "8888"): "测试群"}),
    )
    data = asyncio.run(_api(plugin).list_roles())

    first, second, third = data["entries"]
    assert first["role_name"] == "妲己"
    assert first["group_name"] == "测试群"
    assert first["kind"] == "group"
    assert second["valid"] is False
    assert third["kind"] == "private"
    assert third["label"] == "私聊 10001"


def test_default_role_is_resolved_for_display():
    plugin = FakePlugin(default_role="lucy-voice-daji")
    data = asyncio.run(_api(plugin).list_roles())
    assert data["default"] == {"role_id": "lucy-voice-daji", "name": "妲己"}


def test_set_role_stores_an_exact_role_id():
    plugin = FakePlugin()
    api = _api(plugin, {"platform_id": "qq-main", "conversation": "8888", "role_id": "lucy-voice-daji"})

    assert asyncio.run(api.set_role()) == {"status": "ok", "role_name": "妲己"}
    assert plugin.state.entries == [("qq-main", "8888", "lucy-voice-daji")]


def test_set_role_rejects_an_unknown_role():
    plugin = FakePlugin()
    api = _api(plugin, {"platform_id": "qq-main", "conversation": "8888", "role_id": "nope"})

    assert "角色不存在" in asyncio.run(api.set_role())["error"]
    assert plugin.state.entries == []


def test_set_role_rejects_a_substring_match():
    """A name fragment must not be silently accepted as a role id."""
    plugin = FakePlugin()
    api = _api(plugin, {"platform_id": "qq-main", "conversation": "8888", "role_id": "妲"})

    assert "角色不存在" in asyncio.run(api.set_role())["error"]


def test_set_role_requires_a_target_conversation():
    api = _api(FakePlugin(), {"role_id": "lucy-voice-daji"})
    assert "缺少平台或会话标识" in asyncio.run(api.set_role())["error"]


def test_set_role_reads_an_awaitable_property_body():
    plugin = FakePlugin()
    api = RolePageAPI(plugin)
    api._json = lambda data: data
    api._error = lambda message: {"error": message}
    api._request = AwaitablePropertyRequest(
        {"platform_id": "qq-main", "conversation": "8888", "role_id": "lucy-voice-daji"}
    )

    assert asyncio.run(api.set_role())["status"] == "ok"
    assert plugin.state.entries == [("qq-main", "8888", "lucy-voice-daji")]


def test_set_role_reads_a_plain_property_body():
    plugin = FakePlugin()
    api = RolePageAPI(plugin)
    api._json = lambda data: data
    api._error = lambda message: {"error": message}
    api._request = DictPropertyRequest(
        {"platform_id": "qq-main", "conversation": "8888", "role_id": "lucy-voice-daji"}
    )

    assert asyncio.run(api.set_role())["status"] == "ok"


def test_delete_role_reports_whether_an_entry_existed():
    plugin = FakePlugin(
        state=FakeState(entries=[("qq-main", "8888", "lucy-voice-daji")])
    )
    api = _api(plugin, {"platform_id": "qq-main", "conversation": "8888"})

    assert asyncio.run(api.delete_role()) == {"status": "ok", "removed": True}
    assert plugin.state.entries == []
