"""WebUI backend for per-conversation role overrides."""

from __future__ import annotations

import asyncio

from astrbot.api import logger

from .conversation import describe, is_private
from .roles import BUILTIN_ROLES, Role, resolve_role

PLUGIN_NAME = "astrbot_plugin_qq_aivoice_bridge"


class RolePageAPI:
    def __init__(self, plugin):
        self.plugin = plugin
        self._json = None
        self._error = None
        self._request = None

    def register(self) -> None:
        try:
            from astrbot.api.web import error_response, json_response, request
        except Exception as e:  # noqa: BLE001 - older AstrBot builds have no page API
            logger.warning("[QQ声聊] 当前 AstrBot 不支持插件页面接口：%s", e)
            return
        self._json = json_response
        self._error = error_response
        self._request = request
        routes = [
            ("/page/roles", self.list_roles, ["GET"], "列出会话角色配置"),
            ("/page/roles/set", self.set_role, ["POST"], "设置会话角色"),
            ("/page/roles/delete", self.delete_role, ["POST"], "删除会话角色配置"),
        ]
        for route, handler, methods, desc in routes:
            self.plugin.context.register_web_api(
                f"/{PLUGIN_NAME}{route}",
                handler,
                methods,
                desc,
            )
        logger.info("[QQ声聊] 插件配置页面接口已注册")

    def _catalog(self) -> tuple[list[Role], str]:
        """Return the role list to offer, preferring the live QQ catalog.

        The live catalog is only ever available through a relay group, so when
        nothing is cached the built-in list stands in.
        """
        route = self.plugin.qq.relay_route()
        if route:
            cached = self.plugin.state.get_cached_roles(
                route.platform_id, route.group_id
            )
            if cached:
                return cached, "live"
        return list(BUILTIN_ROLES), "builtin"

    async def _group_names(self, entries) -> dict[tuple[str, str], str]:
        targets = [
            (platform_id, conversation)
            for platform_id, conversation, _ in entries
            if not is_private(conversation)
        ]
        if not targets:
            return {}

        async def lookup(platform_id: str, conversation: str):
            try:
                name = await self.plugin.qq.group_display_name(
                    platform_id, conversation
                )
            except Exception:  # noqa: BLE001 - the name is optional
                name = ""
            return (platform_id, conversation), name

        results = await asyncio.gather(*(lookup(p, c) for p, c in targets))
        return {key: value for key, value in results if value}

    async def _payload(self) -> dict:
        """Read the JSON body of a POST request.

        AstrBot exposes ``request.json`` either as an awaitable function or as
        an awaitable property, depending on the build.
        """
        reader = getattr(self._request, "json", None)
        try:
            if callable(reader):
                data = await reader(default={})
            elif hasattr(reader, "__await__"):
                data = await reader
            else:
                data = reader
        except Exception:  # noqa: BLE001 - a malformed body is a client error
            return {}
        return data if isinstance(data, dict) else {}

    async def list_roles(self):
        catalog, source = self._catalog()
        default_id = self.plugin.config.default_role
        default_role = resolve_role(default_id, catalog) if default_id else None
        entries = self.plugin.state.list_group_roles()
        names = await self._group_names(entries)

        rows = []
        for platform_id, conversation, role_id in entries:
            role = resolve_role(role_id, catalog)
            rows.append(
                {
                    "platform_id": platform_id,
                    "conversation": conversation,
                    "label": describe(conversation),
                    "kind": "private" if is_private(conversation) else "group",
                    "group_name": names.get((platform_id, conversation), ""),
                    "role_id": role_id,
                    "role_name": role.name if role else "",
                    "valid": role is not None,
                }
            )

        return self._json(
            {
                "status": "ok",
                "default": {
                    "role_id": default_role.role_id if default_role else default_id,
                    "name": default_role.name if default_role else default_id,
                },
                "catalog": [
                    {"role_id": role.role_id, "name": role.name} for role in catalog
                ],
                "catalog_source": source,
                "entries": rows,
            }
        )

    async def set_role(self):
        payload = await self._payload()
        platform_id = str(payload.get("platform_id") or "").strip()
        conversation = str(payload.get("conversation") or "").strip()
        role_id = str(payload.get("role_id") or "").strip()
        if not platform_id or not conversation:
            return self._error("缺少平台或会话标识")
        if not role_id:
            return self._error("请选择角色")

        catalog, _ = self._catalog()
        role = resolve_role(role_id, catalog)
        if role is None or role.role_id != role_id:
            return self._error(f"角色不存在：{role_id}")

        self.plugin.state.set_group_role(platform_id, conversation, role.role_id)
        logger.info(
            "[QQ声聊] 页面把会话 %s/%s 的声聊角色设为 %s",
            platform_id,
            conversation,
            role.name,
        )
        return self._json({"status": "ok", "role_name": role.name})

    async def delete_role(self):
        payload = await self._payload()
        platform_id = str(payload.get("platform_id") or "").strip()
        conversation = str(payload.get("conversation") or "").strip()
        if not platform_id or not conversation:
            return self._error("缺少平台或会话标识")

        removed = self.plugin.state.clear_group_role(platform_id, conversation)
        logger.info(
            "[QQ声聊] 页面删除会话 %s/%s 的角色配置（%s）",
            platform_id,
            conversation,
            "已存在" if removed else "原本没有",
        )
        return self._json({"status": "ok", "removed": removed})
