"""Persistent group role overrides and an in-memory QQ role cache.

Only the per-group role overrides are written to disk; they are user settings
and must survive a restart. The role list returned by QQ is cached in memory
with a TTL, so it never adds files or write churn to a long-running process.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .roles import Role

ROLE_CACHE_MAX_ENTRIES = 64


class StateStore:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "state.json"
        self._data: dict = {"group_roles": {}}
        self._role_cache: dict[tuple[str, str], tuple[float, list[Role]]] = {}

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                group_roles = raw.get("group_roles")
                self._data = {
                    "group_roles": group_roles if isinstance(group_roles, dict) else {}
                }
        except Exception:  # noqa: BLE001
            self._data = {"group_roles": {}}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    def get_group_role(self, platform_id: str, group_id: str) -> str:
        return str(
            self._data.get("group_roles", {})
            .get(str(platform_id), {})
            .get(str(group_id), "")
            or ""
        ).strip()

    def set_group_role(self, platform_id: str, group_id: str, role_id: str) -> None:
        platform = self._data.setdefault("group_roles", {}).setdefault(
            str(platform_id), {}
        )
        platform[str(group_id)] = str(role_id)
        self.save()

    def clear_group_role(self, platform_id: str, group_id: str) -> bool:
        group_map = self._data.get("group_roles", {}).get(str(platform_id), {})
        existed = str(group_id) in group_map
        group_map.pop(str(group_id), None)
        if existed:
            self.save()
        return existed

    def get_cached_roles(self, platform_id: str, group_id: str, ttl: int) -> list[Role]:
        if ttl <= 0:
            return []
        key = (str(platform_id), str(group_id))
        item = self._role_cache.get(key)
        if item is None:
            return []
        updated_at, roles = item
        if time.time() - updated_at > ttl:
            self._role_cache.pop(key, None)
            return []
        return list(roles)

    def set_cached_roles(self, platform_id: str, group_id: str, roles: list[Role]) -> None:
        self._role_cache[(str(platform_id), str(group_id))] = (time.time(), list(roles))
        # ponytail: cheapest bounded cache is evicting the oldest write; swap in
        # an LRU only if hit rate on a busy multi-group deployment matters.
        while len(self._role_cache) > ROLE_CACHE_MAX_ENTRIES:
            oldest = min(self._role_cache, key=lambda key: self._role_cache[key][0])
            self._role_cache.pop(oldest, None)
