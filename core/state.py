"""Persistent per-conversation role overrides.

The overrides are user settings, so they are written to disk and survive a
restart.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


class StateStore:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "state.json"
        self._data: dict = {"group_roles": {}}

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

    def get_group_role(self, platform_id: str, conversation: str) -> str:
        return str(
            self._data.get("group_roles", {})
            .get(str(platform_id), {})
            .get(str(conversation), "")
            or ""
        ).strip()

    def set_group_role(
        self, platform_id: str, conversation: str, role_id: str
    ) -> None:
        platform = self._data.setdefault("group_roles", {}).setdefault(
            str(platform_id), {}
        )
        platform[str(conversation)] = str(role_id)
        self.save()

    def clear_group_role(self, platform_id: str, conversation: str) -> bool:
        group_map = self._data.get("group_roles", {}).get(str(platform_id), {})
        existed = str(conversation) in group_map
        group_map.pop(str(conversation), None)
        if existed:
            self.save()
        return existed

    def list_group_roles(self) -> list[tuple[str, str, str]]:
        """Return every stored override as ``(platform_id, conversation, role_id)``.

        The on-disk section is still named ``group_roles`` because earlier
        versions wrote overrides there and the file must stay readable.
        """
        result: list[tuple[str, str, str]] = []
        for platform_id, conversations in self._data.get("group_roles", {}).items():
            if not isinstance(conversations, dict):
                continue
            for conversation, role_id in conversations.items():
                value = str(role_id or "").strip()
                if value:
                    result.append((str(platform_id), str(conversation), value))
        result.sort()
        return result
