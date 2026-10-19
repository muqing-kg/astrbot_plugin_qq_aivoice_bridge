"""Persistence of the per-conversation role overrides."""

from core.state import StateStore


def test_overrides_survive_a_reload(tmp_path):
    store = StateStore(tmp_path)
    store.set_group_role("qq-main", "10086", "lucy-voice-f36")
    store.set_group_role("wx-main", "private:abc", "lucy-voice-f34")

    reloaded = StateStore(tmp_path)
    reloaded.load()

    assert reloaded.get_group_role("qq-main", "10086") == "lucy-voice-f36"
    assert reloaded.get_group_role("wx-main", "private:abc") == "lucy-voice-f34"
    assert reloaded.list_group_roles() == [
        ("qq-main", "10086", "lucy-voice-f36"),
        ("wx-main", "private:abc", "lucy-voice-f34"),
    ]


def test_clearing_an_override_drops_it_from_disk(tmp_path):
    store = StateStore(tmp_path)
    store.set_group_role("qq-main", "10086", "lucy-voice-f36")
    assert store.clear_group_role("qq-main", "10086") is True

    reloaded = StateStore(tmp_path)
    reloaded.load()

    assert reloaded.get_group_role("qq-main", "10086") == ""
    assert reloaded.list_group_roles() == []
