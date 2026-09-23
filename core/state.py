"""Persistent group role overrides and QQ role cache."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .roles import Role


class StateStore:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "state.json"
        self._data: dict = {"group_roles": {}, "role_cache": {}}

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data.update(raw)
        except Exception:  # noqa: BLE001
            self._data = {"group_roles": {}, "role_cache": {}}

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
        item = (
            self._data.get("role_cache", {})
            .get(str(platform_id), {})
            .get(str(group_id))
        )
        if not isinstance(item, dict):
            return []
        try:
            updated_at = float(item.get("updated_at", 0))
        except (TypeError, ValueError):
            return []
        if time.time() - updated_at > ttl:
            return []
        roles = item.get("characters")
        if not isinstance(roles, list):
            return []
        return [
            Role(str(r.get("character_id")), str(r.get("character_name") or r.get("character_id")))
            for r in roles
            if isinstance(r, dict) and r.get("character_id")
        ]

    def set_cached_roles(self, platform_id: str, group_id: str, roles: list[Role]) -> None:
        platform = self._data.setdefault("role_cache", {}).setdefault(
            str(platform_id), {}
        )
        platform[str(group_id)] = {
            "updated_at": time.time(),
            "characters": [
                {"character_id": r.role_id, "character_name": r.name} for r in roles
            ],
        }
        self.save()
