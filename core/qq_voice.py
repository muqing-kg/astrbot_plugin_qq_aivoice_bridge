"""QQ OneBot adapter discovery and AI voice actions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import aiohttp

try:
    from astrbot.api import logger
except ImportError:
    import logging

    logger = logging.getLogger("astrbot")

from .roles import Role, normalize_roles
from .text_utils import brief_error

# A QQ voice clip is a few tens of KB; anything past this is not audio and is
# not worth holding in memory.
MAX_AUDIO_BYTES = 8 * 1024 * 1024


def platform_meta(instance):
    """Return a platform adapter's ``PlatformMetadata``.

    AstrBot exposes it through ``Platform.meta()``. Some adapters also keep the
    same object on ``.metadata``, so that attribute is used as a fallback.
    """
    getter = getattr(instance, "meta", None)
    if callable(getter):
        try:
            meta = getter()
        except Exception:  # noqa: BLE001 - fall back to the attribute below
            meta = None
        if meta is not None:
            return meta
    return getattr(instance, "metadata", None)


@dataclass
class QQAdapter:
    adapter: object
    platform_id: str

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
            metadata = platform_meta(inst)
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
                )
            )
        return result

    def is_configured_qq(self, platform_id: str) -> bool:
        selected = set(self.config.qq_platforms)
        return not selected or str(platform_id) in selected

    async def _with_retries(self, label: str, action):
        """Run one QQ call with the configured timeout and retry budget.

        Every QQ interaction goes through here, so ``timeout`` and
        ``max_retries`` in the plugin config actually apply to role listing,
        voice generation and audio download alike.
        """
        attempts = max(1, 1 + self.config.max_retries)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return await asyncio.wait_for(
                    action(), timeout=self.config.timeout
                )
            except Exception as e:  # noqa: BLE001 - retried, then re-raised
                last_error = e
                if attempt < attempts:
                    logger.warning(
                        "[QQ声聊] %s失败，第 %d 次重试：%s",
                        label,
                        attempt,
                        brief_error(e),
                    )
                    await asyncio.sleep(min(attempt, 3) * 0.5)
        raise last_error if last_error else RuntimeError(f"{label} failed")

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
        raw = await self._with_retries(
            "获取声聊角色",
            lambda: bot.call_action(
                "get_ai_characters",
                group_id=str(group_id),
                chat_type=1,
            ),
        )
        return normalize_roles(raw)

    async def get_ai_record(
        self,
        bot,
        group_id: str,
        character_id: str,
        text: str,
    ) -> str:
        result = await self._with_retries(
            "生成语音",
            lambda: bot.call_action(
                "get_ai_record",
                group_id=str(group_id),
                character=str(character_id),
                text=str(text),
            ),
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
        return await self._with_retries("下载音频", lambda: self._download_once(url))

    async def _download_once(self, url: str) -> bytes:
        timeout = aiohttp.ClientTimeout(total=self.config.timeout)
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=timeout)
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            declared = resp.content_length
            if declared and declared > MAX_AUDIO_BYTES:
                raise RuntimeError(f"audio payload too large: {declared} bytes")
            chunks = bytearray()
            async for chunk in resp.content.iter_chunked(65536):
                chunks.extend(chunk)
                if len(chunks) > MAX_AUDIO_BYTES:
                    raise RuntimeError("audio payload exceeds the size limit")
            data = bytes(chunks)
            content_type = str(resp.headers.get("Content-Type") or "")
        kind = content_type.split(";", 1)[0].strip().lower()
        if kind and not kind.startswith(
            ("audio/", "application/octet-stream", "binary/", "video/")
        ):
            logger.warning(
                "[QQ声聊] 下载语音时 QQ 返回的不是音频类型：%s（%d 字节）",
                kind,
                len(data),
            )
        return data

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
