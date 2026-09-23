"""Small Web API used by the platform-selection page."""

from __future__ import annotations

from functools import partial

from astrbot.api.web import error_response, json_response, request

from .core.qq_voice import platform_meta


async def api_platforms(plugin):
    selected = set(plugin.config.qq_platforms)
    platforms = []
    try:
        instances = plugin.context.platform_manager.get_insts()
    except Exception:  # noqa: BLE001
        instances = []
    for inst in instances:
        metadata = platform_meta(inst)
        if not metadata:
            continue
        platform_id = str(getattr(metadata, "id", "") or "")
        platforms.append(
            {
                "id": platform_id,
                "name": str(
                    getattr(metadata, "adapter_display_name", "")
                    or platform_id
                    or getattr(metadata, "name", "")
                ),
                "type": str(getattr(metadata, "name", "")),
                "selected": platform_id in selected,
            }
        )
    return json_response({"platforms": platforms, "all_qq_when_empty": True})


async def api_config(plugin):
    return json_response({"config": dict(plugin.config._flat)})


async def api_update_platforms(plugin):
    body = await request.json(default={})
    if not isinstance(body, dict):
        return error_response("request body must be a JSON object", status_code=400)
    values = body.get("qq_platforms", [])
    if not isinstance(values, list):
        return error_response("qq_platforms must be a list", status_code=400)
    cleaned = [str(value).strip() for value in values if str(value or "").strip()]
    plugin.config.set("qq_platforms", cleaned)
    plugin.save_config()
    return json_response({"status": "ok", "qq_platforms": cleaned})


def register_web_apis(context, plugin) -> None:
    prefix = "/astrbot_plugin_qq_aivoice_bridge"
    routes = [
        ("platforms", api_platforms, ["GET"], "获取 AstrBot 平台实例"),
        ("config", api_config, ["GET"], "获取插件配置"),
        ("config/platforms", api_update_platforms, ["POST"], "更新 QQ 平台范围"),
    ]
    for path, handler, methods, desc in routes:
        context.register_web_api(
            f"{prefix}/{path}",
            partial(handler, plugin),
            methods,
            desc,
        )
