"""Optional LLM spoken-text polishing."""

from __future__ import annotations

from astrbot.api import logger

from .config import DEFAULT_POLISH_PROMPT
from .text_utils import sanitize_llm_output


async def polish_text(plugin, text: str, uid: str) -> str:
    cfg = plugin.config
    if not cfg.enable_voice_polish:
        return text
    provider_id = cfg.polish_llm_provider
    if not provider_id:
        try:
            provider_id = await plugin.context.get_current_chat_provider_id(uid)
        except Exception:  # noqa: BLE001
            logger.warning("QQ AIVoice: no current LLM provider, skip polish")
            return text

    template = cfg.polish_prompt or DEFAULT_POLISH_PROMPT
    prompt = template.replace("{text}", text)
    try:
        response = await plugin.context.llm_generate(
            chat_provider_id=provider_id,
            prompt=prompt,
        )
        polished = sanitize_llm_output(text, response.completion_text or "")
        if polished:
            if cfg.debug_log:
                logger.info(
                    "QQ AIVoice: polish applied %d -> %d chars",
                    len(text),
                    len(polished),
                )
            return polished
    except Exception as e:  # noqa: BLE001
        logger.warning("QQ AIVoice: polish failed: %s", e)
    return text
