"""QQ OneBot adapter discovery and AI voice actions."""

from __future__ import annotations

from dataclasses import dataclass

import aiohttp

try:
    from astrbot.api import logger
except ImportError:
    import logging

    logger = logging.getLogger("astrbot")

from .roles import Role, normalize_roles


@dataclass
class QQAdapter:
    adapter: object
    platform_id: str
    name: str

    @property
    def bot(self):
        return getattr(self.adapter, "bot", None)


@dataclass
class QQRoute:
    bot: object
    platform_id: str
    group_id: str
    native: bool


class QQVoiceClient:
    def __init__(self, context, config):
        self.context = context
        self.config = config
        self._session: aiohttp.ClientSession | None = None

    def list_qq_adapters(self) -> list[QQAdapter]:
        result: list[QQAdapter] = []
        try:
            instances = self.context.platform_manager.get_insts()
        except Exception:  # noqa: BLE001
            return result
        for inst in instances:
            metadata = getattr(inst, "metadata", None)
            if not metadata:
                continue
            if str(getattr(metadata, "name", "")) != "aiocqhttp":
                continue
            if not getattr(inst, "bot", None):
                continue
            result.append(
                QQAdapter(
                    adapter=inst,
                    platform_id=str(getattr(metadata, "id", "")),
                    name=str(getattr(metadata, "id", "") or getattr(metadata, "name", "")),
                )
            )
        return result

    def is_configured_qq(self, platform_id: str) -> bool:
        selected = set(self.config.qq_platforms)
        return not selected or str(platform_id) in selected

    def _adapter_by_id(self, platform_id: str) -> QQAdapter | None:
        for adapter in self.list_qq_adapters():
            if adapter.platform_id == str(platform_id):
                return adapter
        return None

    def _relay_adapter(self, event=None) -> QQAdapter | None:
        selected = self.config.qq_platforms
        if selected:
            for platform_id in selected:
                adapter = self._adapter_by_id(platform_id)
                if adapter:
                    return adapter
            return None

        if event is not None and event.get_platform_name() == "aiocqhttp":
            adapter = self._adapter_by_id(event.get_platform_id())
            if adapter:
                return adapter

        adapters = self.list_qq_adapters()
        return adapters[0] if adapters else None

    def resolve_route(self, event) -> QQRoute | None:
        current_platform = str(event.get_platform_id() or "")
        current_is_qq = (
            event.get_platform_name() == "aiocqhttp"
            and self.is_configured_qq(current_platform)
        )
        current_group = str(event.get_group_id() or "").strip()

        if current_is_qq and current_group:
            bot = getattr(event, "bot", None)
            if bot:
                return QQRoute(bot, current_platform, current_group, native=True)

        relay_group = self.config.relay_group
        if not relay_group:
            return None
        adapter = self._relay_adapter(event)
        if not adapter or not adapter.bot:
            return None
        return QQRoute(
            adapter.bot,
            adapter.platform_id,
            relay_group,
            native=False,
        )

    async def list_characters(self, bot, group_id: str) -> list[Role]:
        raw = await bot.call_action(
            "get_ai_characters",
            group_id=str(group_id),
            chat_type=1,
        )
        return normalize_roles(raw)

    async def get_ai_record(
        self,
        bot,
        group_id: str,
        character_id: str,
        text: str,
    ) -> str:
        result = await bot.call_action(
            "get_ai_record",
            group_id=str(group_id),
            character=str(character_id),
            text=str(text),
        )
        if isinstance(result, dict):
            return str(
                result.get("url")
                or result.get("audio_url")
                or result.get("file")
                or ""
            ).strip()
        return str(result or "").strip()

    async def download(self, url: str) -> bytes:
        url = str(url or "").strip()
        if not url:
            raise RuntimeError("empty audio URL")
        timeout = aiohttp.ClientTimeout(total=self.config.timeout)
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=timeout)
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
