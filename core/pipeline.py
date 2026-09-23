"""Automatic voice generation and delivery pipeline."""

from __future__ import annotations

import asyncio
import random
import time
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.message_components import File, Plain, Record

from .audio import AudioConverter, VoiceCache, sniff_audio_format
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
from .text_utils import brief_error, extract_plain_text, should_skip

# A background send owns a temp file and the reply it carries, so it is given a
# moment to finish before the plugin stops.
SHUTDOWN_GRACE = 5.0


class VoicePipeline:
    def __init__(self, plugin, qq: QQVoiceClient, converter: AudioConverter):
        self.plugin = plugin
        self.config = plugin.config
        self.qq = qq
        self.converter = converter
        self.cache = VoiceCache()
        self._semaphore = asyncio.Semaphore(self.config.max_concurrency)
        self._pending_tasks: set[asyncio.Task] = set()

    def _track(self, task: asyncio.Task) -> None:
        """Hold a strong reference so a pending send is not garbage collected.

        ``asyncio`` only keeps weak references to tasks, so a fire-and-forget
        send can be collected before it finishes.
        """
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def shutdown(self, grace: float = SHUTDOWN_GRACE) -> None:
        """Let pending background sends finish, then cancel the stragglers."""
        pending = list(self._pending_tasks)
        if not pending:
            return
        _, unfinished = await asyncio.wait(pending, timeout=grace)
        for task in unfinished:
            task.cancel()
        if unfinished:
            await asyncio.gather(*unfinished, return_exceptions=True)

    def _platform_kind(self, event) -> str:
        """Classify the message source without assuming which platform it is."""
        if event.get_platform_name() != "aiocqhttp":
            return "非QQ平台"
        if not self.qq.is_configured_qq(event.get_platform_id()):
            return "非QQ平台"
        return "QQ群" if str(event.get_group_id() or "").strip() else "QQ私聊"

    async def handle_decorating_result(self, event) -> None:
        cfg = self.config
        if not cfg.enabled or not cfg.auto_tts:
            return
        result = event.get_result()
        if not result or not result.chain or not result.is_llm_result():
            return

        kind = self._platform_kind(event)
        if random.random() > cfg.probability:
            logger.info("[QQ声聊] 识别到%s消息，但本次未命中触发概率，按文字发送", kind)
            return

        original_text = extract_plain_text(result.chain)
        if should_skip(original_text, cfg.min_text_length, cfg.max_text_length):
            logger.info("[QQ声聊] 识别到%s消息，但文本长度不在处理范围，按文字发送", kind)
            return

        started = time.monotonic()
        logger.debug(
            "[QQ声聊] 来源适配器 %s，实例 %s",
            event.get_platform_name(),
            event.get_platform_id(),
        )
        uid = event.unified_msg_origin
        text = await polish_text(self.plugin, original_text, uid)
        display_text = text if cfg.display_polished_text else original_text

        route = self.qq.resolve_route(event)
        if not route:
            logger.info(
                "[QQ声聊] 识别到%s消息，但没有可用的 QQ 中转群，本条按文字发送",
                kind,
            )
            await self._safe_send_text(event, display_text)
            result.chain = []
            return

        if route.native:
            logger.info("[QQ声聊] 识别到%s消息 → 当前群直接生成语音", kind)
        else:
            logger.info("[QQ声聊] 识别到%s消息 → 通过 QQ 中转群生成语音", kind)

        if cfg.enable_segmentation:
            await self._handle_segments(event, result, route, text, display_text)
        else:
            await self._handle_single(event, result, route, text, display_text)
        logger.info("[QQ声聊] 本次处理完成，总耗时 %.1f 秒", time.monotonic() - started)

    async def _handle_single(self, event, result, route: QQRoute, text: str, display_text: str) -> None:
        roles = await self._roles_for_route(route)
        role = self._pick_role(event, route, roles)
        include_text = self.config.send_text_with_tts
        if role is None:
            logger.info("[QQ声聊] 没有可用的声聊角色，本条按文字发送")
            await self._safe_send_text(event, display_text)
            result.chain = []
            return

        text_sent = False
        if self.config.send_text_async and include_text:
            text_sent = await self._safe_send_text(event, display_text)

        if route.native:
            if include_text and not text_sent:
                text_sent = await self._safe_send_text(event, display_text)
            logger.info("[QQ声聊] 发送形式：QQ 服务端直发语音")
            ok = await self._native_generate(route, role, text)
            if not ok and not text_sent:
                logger.info("[QQ声聊] QQ 声聊生成失败，本条改发文字")
                await self._safe_send_text(event, display_text)
            result.chain = []
            return

        path = await self._generate_file(route, role, text)
        if path is None:
            logger.info("[QQ声聊] 语音合成失败，本条改发文字")
            if not text_sent:
                await self._safe_send_text(event, display_text)
            result.chain = []
            return

        text_part = display_text if include_text else ""
        if self.config.send_text_async:
            if include_text and not text_sent:
                text_sent = await self._safe_send_text(event, display_text)
            if text_sent:
                # The text already went out, so the background send must not
                # repeat it alongside the voice.
                text_part = ""
            logger.info("[QQ声聊] 发送形式：先发文字，语音后台补发")
            # The background task owns the temp file and deletes it when done.
            self._track(
                asyncio.create_task(
                    self._send_audio_later(
                        event,
                        path,
                        text_part,
                        "" if text_sent else display_text,
                    )
                )
            )
        else:
            logger.info("[QQ声聊] 发送形式：本地合成语音消息")
            try:
                await self._send_audio(event, path, text_part)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "[QQ声聊] 语音消息发送失败，本条改发文字：%s", brief_error(e)
                )
                if not text_sent:
                    await self._safe_send_text(event, display_text)
            finally:
                self._discard(path)
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
        # The text shown in chat can differ from the text being spoken (polish
        # may be hidden), so it is split by the same rule and paired by index.
        display_segments = (
            segments
            if display_text == text
            else split_text(display_text, cfg.segment_pattern, cfg.segment_max_count)
        )
        roles = await self._roles_for_route(route)
        role = self._pick_role(event, route, roles)

        logger.info("[QQ声聊] 文本分为 %d 段，逐段生成语音", len(plans))
        voice_count = 0
        text_count = 0
        text_shown = False
        if len(display_segments) != len(plans):
            # Polishing rewrote the sentence count, so segments can no longer be
            # matched to the original wording one by one. Show the original text
            # once and keep the segments voice-only instead of misaligning them.
            logger.info(
                "[QQ声聊] 展示文本 %d 段与语音 %d 段不一致，改为整段展示原文",
                len(display_segments),
                len(plans),
            )
            sent = await self._send_text_if(
                event, display_text, cfg.send_text_with_tts
            )
            text_count += sent
            text_shown = bool(sent)
            display_segments = [""] * len(plans)
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
            shown = display_segments[index] if index < len(display_segments) else ""
            # Text-only deliveries (short segment, no role, failed synthesis)
            # still have to say something, so they fall back to the spoken
            # wording unless the whole text already went out above.
            text_only = "" if text_shown else (shown or plan.text)
            if delivery == TEXT_FALLBACK:
                text_count += await self._send_text_if(event, text_only, True)
                continue
            if delivery == DROP:
                continue
            if role is None:
                # Without a role nothing can be spoken, so the reply falls back
                # to text regardless of the fallback switch, matching the
                # single-segment path instead of vanishing.
                text_count += await self._send_text_if(event, text_only, True)
                continue

            # Remember whether this segment's text already went out, so a later
            # failure does not repeat it.
            sent = await self._send_text_if(event, shown, delivery == TEXT_FIRST)
            text_count += sent
            text_sent = bool(sent)

            if route.native:
                bundled = delivery == BUNDLED and cfg.send_text_with_tts
                extra = await self._send_text_if(event, shown, bundled)
                text_count += extra
                text_sent = text_sent or bool(extra)
                ok = await self._native_generate(route, role, plan.text)
                if ok:
                    voice_count += 1
                text_count += await self._send_text_if(
                    event,
                    text_only,
                    not ok and not text_sent and cfg.segment_text_fallback,
                )
                continue

            path = await self._generate_file(route, role, plan.text)
            if path is None:
                text_count += await self._send_text_if(
                    event,
                    text_only,
                    not text_sent and cfg.segment_text_fallback,
                )
                continue
            text_part = "" if delivery in {VOICE_ONLY, TEXT_FIRST} else shown
            if delivery == TEXT_FIRST:
                # This segment's text is already out, so the voice may be
                # generated and sent in the background. The task owns the temp
                # file from here on, so this branch must not discard it.
                logger.info("[QQ声聊] 分段发送形式：先发文字，语音后台补发")
                self._track(
                    asyncio.create_task(
                        self._send_audio_later(
                            event,
                            path,
                            text_part,
                            "" if text_sent else text_only,
                        )
                    )
                )
                voice_count += 1
                continue
            try:
                await self._send_audio(event, path, text_part)
                voice_count += 1
            except Exception as e:  # noqa: BLE001
                logger.warning("[QQ声聊] 分段语音发送失败：%s", brief_error(e))
                text_count += await self._send_text_if(
                    event,
                    text_only,
                    not text_sent and cfg.segment_text_fallback,
                )
            finally:
                self._discard(path)

        logger.info("[QQ声聊] 本次发送语音 %d 条，文字 %d 条", voice_count, text_count)
        result.chain = []

    async def _roles_for_route(self, route: QQRoute) -> list[Role]:
        cached = self.plugin.state.get_cached_roles(route.platform_id, route.group_id)
        if cached:
            logger.debug("[QQ声聊] 复用内存中的角色列表，共 %d 个", len(cached))
            return cached
        roles = await self.qq.list_characters(route.bot, route.group_id)
        if roles:
            self.plugin.state.set_cached_roles(
                route.platform_id,
                route.group_id,
                roles,
            )
            logger.info("[QQ声聊] 已从 QQ 获取到 %d 个声聊角色", len(roles))
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
                logger.info("[QQ声聊] 使用本群单独指定的角色：%s", role.name)
                return role
        role = resolve_role(self.config.default_role, roles) or roles[0]
        logger.info("[QQ声聊] 使用全局默认角色：%s", role.name)
        return role

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
            logger.info("[QQ声聊] QQ 声聊已生成语音")
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("[QQ声聊] QQ 声聊生成失败：%s", brief_error(e))
            return False

    async def _generate_file(self, route: QQRoute, role: Role, text: str) -> Path | None:
        fmt = self.config.audio_format
        key = self.cache.cache_key(role.role_id, fmt, text)
        cached = self.cache.get(key)
        if cached:
            data, actual = cached
            logger.info("[QQ声聊] 命中内存缓存，跳过语音合成")
            return self._write_temp(data, actual)

        logger.info("[QQ声聊] 内存缓存未命中，开始请求 QQ 声聊")
        started = time.monotonic()
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
            if source == "bin":
                logger.warning(
                    "[QQ声聊] 无法识别 QQ 返回的音频格式（%d 字节，前 16 字节：%s）",
                    len(raw),
                    raw[:16].hex(" "),
                )
            if source != fmt:
                logger.info("[QQ声聊] 音频转换：%s → %s", source.upper(), fmt.upper())
            converted, actual = await self.converter.convert(raw, fmt, source_format=source)
            self.cache.put(key, converted, actual)
            path = self._write_temp(converted, actual)
            logger.debug(
                "[QQ声聊] 合成细节：角色 %s，源格式 %s，输出格式 %s",
                role.role_id,
                source,
                actual,
            )
            logger.info(
                "[QQ声聊] 语音合成完成，耗时 %.1f 秒，音频 %.1f KB",
                time.monotonic() - started,
                len(converted) / 1024,
            )
            return path
        except Exception as e:  # noqa: BLE001
            logger.warning("[QQ声聊] 语音合成失败：%s", brief_error(e))
            return None

    def _write_temp(self, data: bytes, fmt: str) -> Path:
        path = self.converter.new_temp_path(fmt)
        path.write_bytes(data)
        return path

    @staticmethod
    def _discard(path: Path) -> None:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass

    async def _send_audio_later(
        self,
        event,
        path: Path,
        text: str,
        fallback_text: str = "",
    ) -> None:
        try:
            await self._send_audio(event, path, text)
        except Exception as e:  # noqa: BLE001
            logger.warning("[QQ声聊] 后台补发语音失败：%s", brief_error(e))
            if fallback_text:
                logger.info("[QQ声聊] 本条改发文字")
                await self._safe_send_text(event, fallback_text)
        finally:
            self._discard(path)

    async def _send_audio(self, event, path: Path, text: str) -> None:
        chain = []
        if text:
            chain.append(Plain(text))
        try:
            chain.append(Record.fromFileSystem(str(path)))
            await event.send(MessageChain(chain))
            logger.info("[QQ声聊] 语音已发送")
            return
        except Exception as e:  # noqa: BLE001
            logger.warning("[QQ声聊] 语音消息发送失败，改发音频文件：%s", brief_error(e))

        file_chain = []
        if text:
            file_chain.append(Plain(text))
        file_chain.append(File(file=str(path), name=path.name))
        await event.send(MessageChain(file_chain))
        logger.info("[QQ声聊] 音频文件已发送")

    async def _safe_send_text(self, event, text: str) -> bool:
        """Send plain text; returns True when something was actually sent."""
        value = str(text or "").strip()
        if not value:
            return False
        try:
            await event.send(MessageChain([Plain(value)]))
            logger.info("[QQ声聊] 文字已发送")
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("[QQ声聊] 文字发送失败：%s", brief_error(e))
            return False

    async def _send_text_if(self, event, text: str, enabled: bool) -> int:
        """Send text only when enabled, returning 1 on success for counting."""
        if not enabled:
            return 0
        return int(await self._safe_send_text(event, text))
