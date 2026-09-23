"""AstrBot plugin entry point."""

from __future__ import annotations

from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star, StarTools

from .core.audio import AudioConverter, purge_legacy_cache_dir
from .core.config import ConfigManager
from .core.pipeline import VoicePipeline
from .core.qq_voice import QQVoiceClient
from .core.state import StateStore
from .handlers.commands import handle_role_command


class QQAIVoiceBridgePlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = ConfigManager(config)
        self.data_dir = Path(StarTools.get_data_dir())
        self.state = StateStore(self.data_dir)
        self.state.load()
        self.converter = AudioConverter(
            self.data_dir / "temp",
            ffmpeg_path=self.config.ffmpeg_path,
        )
        leftover = self.converter.purge_temp_files()
        if purge_legacy_cache_dir(self.data_dir):
            logger.info("[QQ声聊] 已清除旧版本的磁盘音频缓存目录")
        if leftover:
            logger.info("[QQ声聊] 已清理上次运行残留的 %d 个音频文件", leftover)
        logger.info(
            "[QQ声聊] 插件已启用：音色缓存只驻留内存，音频文件发送后立即删除"
        )
        self.qq = QQVoiceClient(context, self.config)
        self.pipeline = VoicePipeline(self, self.qq, self.converter)

    @filter.on_decorating_result()
    async def on_decorating_result(self, event):
        await self.pipeline.handle_decorating_result(event)

    @filter.command("声聊角色")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def role_command(self, event):
        yield event.plain_result(await handle_role_command(self, event))

    async def terminate(self):
        await self.pipeline.shutdown()
        await self.qq.close()
