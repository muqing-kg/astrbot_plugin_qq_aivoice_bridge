"""Optional LLM spoken-text polishing."""

from __future__ import annotations

try:
    from astrbot.api import logger
except ImportError:
    import logging

    logger = logging.getLogger("astrbot")

from .config import DEFAULT_POLISH_PROMPT
from .text_utils import sanitize_llm_output

POLISH_PREVIEW_LIMIT = 80


def _preview(text: str) -> str:
    value = str(text or "").strip()
    if len(value) <= POLISH_PREVIEW_LIMIT:
        return value
    return f"{value[:POLISH_PREVIEW_LIMIT]}…（后略）"


async def polish_text(plugin, text: str, uid: str) -> str:
    cfg = plugin.config
    if not cfg.enable_voice_polish:
        return text
    provider_id = cfg.polish_llm_provider
    if not provider_id:
        try:
            provider_id = await plugin.context.get_current_chat_provider_id(uid)
        except Exception:  # noqa: BLE001
            logger.warning("[QQ声聊] 没有可用的 LLM Provider，跳过口播润色")
            return text

    template = cfg.polish_prompt or DEFAULT_POLISH_PROMPT
    prompt = template.replace("{text}", text)
    try:
        response = await plugin.context.llm_generate(
            chat_provider_id=provider_id,
            prompt=prompt,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[QQ声聊] 口播润色失败，改用原文：%s", e)
        return text

    polished = sanitize_llm_output(text, response.completion_text or "")
    if not polished:
        logger.warning(
            "[QQ声聊] 口播润色结果不可用（返回为空或偏离原文太多），改用原文"
        )
        return text
    if polished == text:
        logger.info("[QQ声聊] 口播润色完成，模型未改动文本")
        return polished
    logger.info(
        "[QQ声聊] 口播润色完成（%d 字 → %d 字）：%s",
        len(text),
        len(polished),
        _preview(polished),
    )
    return polished
