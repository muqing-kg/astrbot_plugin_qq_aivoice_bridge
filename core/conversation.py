"""Conversation identity for per-chat role overrides.

An override belongs to the conversation the user typed in, not to the QQ group
that synthesises the voice. Every relayed platform shares one relay group, so
keying overrides by the relay group would let one chat overwrite another.
"""

from __future__ import annotations

PRIVATE_PREFIX = "private:"


def conversation_key(event) -> tuple[str, str]:
    """Return ``(platform_id, conversation)`` for the message source.

    Groups keep the bare group id so overrides written by earlier versions stay
    valid. Private chats are namespaced because their id space is the sender's,
    which could otherwise collide with a group id.
    """
    platform_id = str(event.get_platform_id() or "")
    group_id = str(event.get_group_id() or "").strip()
    if group_id:
        return platform_id, group_id

    getter = getattr(event, "get_sender_id", None)
    sender_id = str(getter() or "").strip() if callable(getter) else ""
    if not sender_id:
        return platform_id, ""
    return platform_id, f"{PRIVATE_PREFIX}{sender_id}"


def is_private(conversation: str) -> bool:
    return str(conversation or "").startswith(PRIVATE_PREFIX)


def describe(conversation: str) -> str:
    """Return a human-readable label for a stored conversation key."""
    value = str(conversation or "").strip()
    if not value:
        return "未知会话"
    if is_private(value):
        return f"私聊 {value[len(PRIVATE_PREFIX):]}"
    return f"群 {value}"
