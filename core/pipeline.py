"""Automatic voice generation and delivery pipeline."""

from __future__ import annotations

import asyncio
import random
import time
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.message_components import File, Plain, Record

from .audio import AudioConverter, sniff_audio_format
from .polish import polish_text
from .qq_voice import QQRoute, QQVoiceClient
from .roles import Role, resolve_role
from .segmentation import (
    BUNDLED,
    DROP,
    TEXT_FALLBACK,
    TEXT_FIRST,
    VOICE_ONLY,
    plan_segments,
    resolve_delivery,
    split_text,
)
from .text_utils import extract_plain_text, should_skip

ROLE_CACHE_TTL = 3600


class VoicePipeline:
    def __init__(self, plugin, qq: QQVoiceClient, converter: AudioConverter):
        self.plugin = plugin
        self.config = plugin.config
        self.qq = qq
        self.converter = converter
        self._semaphore = asyncio.Semaphore(self.config.max_concurrency)
        self._temp_dir = Path(converter.cache_dir).parent / "temp"
        self._temp_dir.mkdir(parents=True, exist_ok=True)

    async def handle_decorating_result(self, event) -> None:
        cfg = self.config
        if not cfg.enabled or not cfg.auto_tts:
            return
        result = event.get_result()
        if not result or not result.chain or not result.is_llm_result():
            return
        if random.random() > cfg.probability:
            return

        original_text = extract_plain_text(result.chain)
        if should_skip(original_text, cfg.min_text_length, cfg.max_text_length):
            return

        uid = event.unified_msg_origin
        text = await polish_text(self.plugin, original_text, uid)
        display_text = text if cfg.display_polished_text else original_text

        route = self.qq.resolve_route(event)
        if not route:
            if cfg.send_text_with_tts:
                await self._safe_send_text(event, display_text)
            result.chain = []
            return

        if cfg.enable_segmentation:
            await self._handle_segments(event, result, route, text, display_text)
        else:
            await self._handle_single(event, result, route, text, display_text)

    async def _handle_single(self, event, result, route: QQRoute, text: str, display_text: str) -> None:
        roles = await self._roles_for_route(route)
        role = self._pick_role(event, route, roles)
        include_text = self.config.send_text_with_tts
        if role is None:
            if include_text:
                await self._safe_send_text(event, display_text)
            result.chain = []
            return

        text_sent = False
        if self.config.send_text_async and include_text:
            text_sent = await self._safe_send_text(event, display_text)

        if route.native:
            if include_text and not text_sent:
                text_sent = await self._safe_send_text(event, display_text)
            ok = await self._native_generate(route, role, text)
            if not ok and include_text and not text_sent:
                await self._safe_send_text(event, display_text)
            result.chain = []
            return

        path = await self._generate_file(route, role, text)
        if path is None:
            if include_text and not text_sent:
                await self._safe_send_text(event, display_text)
            result.chain = []
            return

        if self.config.send_text_async:
            if include_text and not text_sent:
                text_sent = await self._safe_send_text(event, display_text)
            asyncio.create_task(
                self._send_audio_later(
                    event,
                    path,
                    "" if text_sent or not include_text else display_text,
                )
            )
        else:
            await self._send_audio(event, path, display_text if include_text else "")
        result.chain = []

    async def _handle_segments(
        self,
        event,
        result,
        route: QQRoute,
        text: str,
        display_text: str,
    ) -> None:
        cfg = self.config
        segments = split_text(text, cfg.segment_pattern, cfg.segment_max_count)
        plans = plan_segments(
            segments,
            min_length=cfg.min_text_length,
            probability=cfg.segment_voice_probability,
        )
        roles = await self._roles_for_route(route)
        role = self._pick_role(event, route, roles)

        for index, plan in enumerate(plans):
            if plan.blank:
                continue
            delivery = resolve_delivery(
                short=plan.short,
                want_voice=plan.want_voice,
                text_enabled=cfg.send_text_with_tts,
                text_async=cfg.send_text_async,
                fallback_enabled=cfg.segment_text_fallback,
            )
            shown = display_text if len(plans) == 1 else plan.text
            if delivery in {TEXT_FALLBACK, DROP}:
                if delivery == TEXT_FALLBACK:
                    await self._safe_send_text(event, shown)
                continue
            if role is None:
                if cfg.segment_text_fallback:
                    await self._safe_send_text(event, shown)
                continue

            if delivery == TEXT_FIRST:
                await self._safe_send_text(event, shown)

            if route.native:
                if delivery == BUNDLED and cfg.send_text_with_tts:
                    await self._safe_send_text(event, shown)
                ok = await self._native_generate(route, role, plan.text)
                if not ok and cfg.segment_text_fallback:
                    await self._safe_send_text(event, shown)
                continue

            path = await self._generate_file(route, role, plan.text)
            if path is None:
                if cfg.segment_text_fallback:
                    await self._safe_send_text(event, shown)
                continue
            if delivery == VOICE_ONLY or delivery == TEXT_FIRST:
                await self._send_audio(event, path, "")
            else:
                await self._send_audio(event, path, shown)

        result.chain = []

    async def _roles_for_route(self, route: QQRoute) -> list[Role]:
        cached = self.plugin.state.get_cached_roles(
            route.platform_id,
            route.group_id,
            ROLE_CACHE_TTL,
        )
        if cached:
            return cached
        roles = await self.qq.list_characters(route.bot, route.group_id)
        if roles:
            self.plugin.state.set_cached_roles(
                route.platform_id,
                route.group_id,
                roles,
            )
        return roles

    async def native_group_roles(self, event) -> tuple[QQRoute, list[Role]] | None:
        route = self.qq.resolve_route(event)
        if not route or not route.native:
            return None
        return route, await self._roles_for_route(route)

    def _pick_role(self, event, route: QQRoute, roles: list[Role]) -> Role | None:
        if not roles:
            return None
        if route.native:
            group_id = str(event.get_group_id() or "")
            override = self.plugin.state.get_group_role(route.platform_id, group_id)
            role = resolve_role(override, roles)
            if role:
                return role
        return resolve_role(self.config.default_role, roles) or roles[0]

    async def _native_generate(self, route: QQRoute, role: Role, text: str) -> bool:
        try:
            url = await self.qq.get_ai_record(
                route.bot,
                route.group_id,
                role.role_id,
                text,
            )
            if not url:
                raise RuntimeError("empty audio URL")
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("QQ AIVoice: native generation failed: %s", e)
            return False

    async def _generate_file(self, route: QQRoute, role: Role, text: str) -> Path | None:
        fmt = self.config.audio_format
        key = self.converter.cache_key(role.role_id, fmt, text)
        cached = self.converter.get_cache(key)
        if cached:
            data, actual = cached
            return self._write_temp(data, actual)

        try:
            async with self._semaphore:
                url = await self.qq.get_ai_record(
                    route.bot,
                    route.group_id,
                    role.role_id,
                    text,
                )
                if not url:
                    raise RuntimeError("empty audio URL")
                raw = await self.qq.download(url)
            source = sniff_audio_format(raw)
            converted, actual = await self.converter.convert(raw, fmt, source_format=source)
            if self.config.cache_ttl > 0:
                path = self.converter.put_cache(key, converted, actual)
            else:
                path = self._write_temp(converted, actual)
            if self.config.debug_log:
                logger.info(
                    "QQ AIVoice: generated role=%s source=%s target=%s actual=%s",
                    role.role_id,
                    source,
                    fmt,
                    actual,
                )
            return path
        except Exception as e:  # noqa: BLE001
            logger.warning("QQ AIVoice: generation failed: %s", e)
            return None

    def _write_temp(self, data: bytes, fmt: str) -> Path:
        path = self._temp_dir / f"qq_aivoice_{int(time.time() * 1000)}.{fmt}"
        path.write_bytes(data)
        return path

    async def _send_audio_later(self, event, path: Path, text: str) -> None:
        try:
            await self._send_audio(event, path, text)
        except Exception as e:  # noqa: BLE001
            logger.warning("QQ AIVoice: background audio send failed: %s", e)

    async def _send_audio(self, event, path: Path, text: str) -> None:
        chain = []
        if text:
            chain.append(Plain(text))
        try:
            chain.append(Record.fromFileSystem(str(path)))
            await event.send(MessageChain(chain))
            return
        except Exception as e:  # noqa: BLE001
            logger.warning("QQ AIVoice: record send failed, fallback to file: %s", e)

        file_chain = []
        if text:
            file_chain.append(Plain(text))
        file_chain.append(File(file=str(path), name=path.name))
        await event.send(MessageChain(file_chain))

    async def _safe_send_text(self, event, text: str) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        try:
            await event.send(MessageChain([Plain(value)]))
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("QQ AIVoice: text send failed: %s", e)
            return False
