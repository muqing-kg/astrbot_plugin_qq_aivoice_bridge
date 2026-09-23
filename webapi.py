"""Small Web API used by the platform-selection page."""

from __future__ import annotations

from functools import partial


async def api_platforms(plugin):
    from quart import jsonify

    selected = set(plugin.config.qq_platforms)
    platforms = []
    try:
        instances = plugin.context.platform_manager.get_insts()
    except Exception:  # noqa: BLE001
        instances = []
    for inst in instances:
        metadata = getattr(inst, "metadata", None)
        if not metadata:
            continue
        platforms.append(
            {
                "id": str(getattr(metadata, "id", "")),
                "name": str(getattr(metadata, "id", "") or getattr(metadata, "name", "")),
                "type": str(getattr(metadata, "name", "")),
                "selected": str(getattr(metadata, "id", "")) in selected,
            }
        )
    return jsonify({"platforms": platforms, "all_qq_when_empty": True})


async def api_config(plugin):
    from quart import jsonify

    return jsonify({"config": dict(plugin.config._flat)})


async def api_update_platforms(plugin):
    from quart import jsonify, request

    body = await request.json
    values = body.get("qq_platforms", [])
    if not isinstance(values, list):
        return jsonify({"error": "qq_platforms must be a list"}), 400
    cleaned = [str(value).strip() for value in values if str(value or "").strip()]
    plugin.config.set("qq_platforms", cleaned)
    plugin.save_config()
    return jsonify({"status": "ok", "qq_platforms": cleaned})


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
