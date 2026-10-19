"""Conversation identity used to key per-chat role overrides."""

from __future__ import annotations

from core.conversation import conversation_key, describe, is_private


class FakeEvent:
    def __init__(self, platform_id="qq-main", group_id="8888", sender_id="10001"):
        self._platform_id = platform_id
        self._group_id = group_id
        self._sender_id = sender_id

    def get_platform_id(self):
        return self._platform_id

    def get_group_id(self):
        return self._group_id

    def get_sender_id(self):
        return self._sender_id


class EventWithoutSender(FakeEvent):
    get_sender_id = None


def test_group_key_is_the_bare_group_id():
    """Earlier versions stored bare group ids; those overrides must stay valid."""
    assert conversation_key(FakeEvent()) == ("qq-main", "8888")


def test_private_key_is_namespaced_by_sender():
    key = conversation_key(FakeEvent(group_id="", sender_id="10001"))
    assert key == ("qq-main", "private:10001")


def test_private_key_without_sender_is_empty():
    event = EventWithoutSender(group_id="")
    assert conversation_key(event) == ("qq-main", "")


def test_missing_platform_degrades_to_empty_string():
    assert conversation_key(FakeEvent(platform_id=None))[0] == ""


def test_is_private():
    assert is_private("private:10001")
    assert not is_private("8888")
    assert not is_private("")


def test_describe():
    assert describe("8888") == "群 8888"
    assert describe("private:10001") == "私聊 10001"
    assert describe("") == "未知会话"
