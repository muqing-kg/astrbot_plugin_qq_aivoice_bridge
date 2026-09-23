"""AstrBot plugin entry point."""

from __future__ import annotations

import re
from pathlib import Path

from astrbot.api.event import filter
from astrbot.api.star import Context, Star, StarTools

from .core.audio import AudioConverter
from .core.config import ConfigManager
from .core.pipeline import VoicePipeline
from .core.qq_voice import QQVoiceClient
from .core.state import StateStore
from .handlers.commands import handle_role_command
from .webapi import register_web_apis


class QQAIVoiceBridgePlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self._astrbot_config = config
        self.config = ConfigManager(config)
        self.data_dir = Path(StarTools.get_data_dir())
        self.state = StateStore(self.data_dir)
        self.state.load()
        self.converter = AudioConverter(
            self.data_dir / "cache",
            ffmpeg_path=self.config.ffmpeg_path,
            cache_ttl=self.config.cache_ttl,
            max_cache_mb=self.config.max_cache_mb,
        )
        self.qq = QQVoiceClient(context, self.config)
        self.pipeline = VoicePipeline(self, self.qq, self.converter)
        register_web_apis(context, self)

    @filter.on_decorating_result()
    async def on_decorating_result(self, event):
        await self.pipeline.handle_decorating_result(event)

    @filter.command("声聊角色")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def role_command(self, event):
        yield event.plain_result(await handle_role_command(self, event))

    async def terminate(self):
        await self.qq.close()

    def save_config(self) -> None:
        save = getattr(self._astrbot_config, "save_config", None)
        if callable(save):
            save()

    @staticmethod
    def _parse_cmd(event, cmd: str) -> str:
        raw = str(event.message_str or "").strip()
        base = cmd.lstrip("/")
        match = re.match(
            rf"^/?{re.escape(base)}(?:@[^\s]+)?(?:\s+|$)",
            raw,
            re.IGNORECASE,
        )
        if match:
            return raw[match.end():].strip()
        return raw[len(cmd):].strip()
