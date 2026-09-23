"""Verified QQ AI voice role registry.

The built-in list is a fallback. Runtime ``get_ai_characters`` output is
always preferred.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Role:
    role_id: str
    name: str


BUILTIN_ROLES: tuple[Role, ...] = (
    Role("lucy-voice-laibixiaoxin", "小新"),
    Role("lucy-voice-houge", "猴哥"),
    Role("lucy-voice-silang", "四郎"),
    Role("lucy-voice-guangdong-f1", "东北老妹儿"),
    Role("lucy-voice-guangxi-m1", "广西大表哥"),
    Role("lucy-voice-daji", "妲己"),
    Role("lucy-voice-lizeyan", "霸道总裁"),
    Role("lucy-voice-suxinjiejie", "酥心御姐"),
    Role("lucy-voice-m8", "说书先生"),
    Role("lucy-voice-male1", "憨憨小弟"),
    Role("lucy-voice-male3", "憨厚老哥"),
    Role("lucy-voice-lvbu", "吕布"),
    Role("lucy-voice-xueling", "元气少女"),
    Role("lucy-voice-f37", "文艺少女"),
    Role("lucy-voice-male2", "磁性大叔"),
    Role("lucy-voice-female1", "邻家小妹"),
    Role("lucy-voice-m14", "低沉男声"),
    Role("lucy-voice-f38", "傲娇少女"),
    Role("lucy-voice-m101", "爹系男友"),
    Role("lucy-voice-female2", "暖心姐姐"),
    Role("lucy-voice-f36", "温柔妹妹"),
    Role("lucy-voice-f34", "书香少女"),
)

ROLE_BY_ID = {role.role_id: role for role in BUILTIN_ROLES}
ROLE_BY_NAME = {role.name: role for role in BUILTIN_ROLES}


def normalize_roles(raw) -> list[Role]:
    """Flatten one or more ``get_ai_characters`` categories.

    Deduplicates by role ID while preserving the first occurrence.
    """
    if not raw:
        return []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []

    result: list[Role] = []
    seen: set[str] = set()
    for category in raw:
        if not isinstance(category, dict):
            continue
        characters = category.get("characters")
        if not isinstance(characters, list):
            continue
        for item in characters:
            if not isinstance(item, dict):
                continue
            role_id = str(item.get("character_id") or "").strip()
            name = str(item.get("character_name") or role_id).strip()
            if not role_id or role_id in seen:
                continue
            seen.add(role_id)
            result.append(Role(role_id, name or role_id))
    return result


def resolve_role(token: str, roles: list[Role] | None = None) -> Role | None:
    """Resolve a role by 1-based number, ID, or Chinese name."""
    raw = str(token or "").strip()
    if not raw:
        return None

    role_list = list(roles or BUILTIN_ROLES)
    if raw.isdigit():
        index = int(raw) - 1
        if 0 <= index < len(role_list):
            return role_list[index]

    for role in role_list:
        if raw == role.role_id or raw == role.name:
            return role

    for role in role_list:
        if raw in role.name or raw in role.role_id:
            return role
    return None


def role_number(role_id: str, roles: list[Role] | None = None) -> int | None:
    for index, role in enumerate(roles or BUILTIN_ROLES, 1):
        if role.role_id == role_id:
            return index
    return None


def format_role_list(roles: list[Role] | None = None) -> str:
    return "\n".join(
        f"{index}. {role.name}"
        for index, role in enumerate(roles or BUILTIN_ROLES, 1)
    )

