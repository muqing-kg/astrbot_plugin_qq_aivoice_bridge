"""Bounds on the in-memory state a long-running process accumulates."""

from core.roles import Role
from core.state import ROLE_CACHE_MAX_ENTRIES, StateStore

ROLE = Role("lucy-voice-f36", "温柔妹妹")


def test_role_cache_stays_bounded(tmp_path):
    store = StateStore(tmp_path)
    total = ROLE_CACHE_MAX_ENTRIES * 3
    for index in range(total):
        store.set_cached_roles("qq-main", f"group{index}", [ROLE])

    assert len(store._role_cache) == ROLE_CACHE_MAX_ENTRIES
    assert store.get_cached_roles("qq-main", f"group{total - 1}", 3600) == [ROLE]
