from core.roles import (
    BUILTIN_ROLES,
    format_role_list,
    normalize_roles,
    resolve_role,
)


def test_roles_are_deduplicated_by_id():
    raw = [
        {
            "type": "推荐",
            "characters": [
                {"character_id": "a", "character_name": "甲"},
                {"character_id": "b", "character_name": "乙"},
            ],
        },
        {
            "type": "其他",
            "characters": [
                {"character_id": "a", "character_name": "甲"},
                {"character_id": "c", "character_name": "丙"},
            ],
        },
    ]
    assert [r.role_id for r in normalize_roles(raw)] == ["a", "b", "c"]


def test_role_resolution_by_number_name_and_id():
    assert resolve_role("1").name == BUILTIN_ROLES[0].name
    assert resolve_role("温柔妹妹").role_id == "lucy-voice-f36"
    assert resolve_role("lucy-voice-f36").name == "温柔妹妹"


def test_role_list_is_numbered():
    lines = format_role_list(BUILTIN_ROLES[:2]).splitlines()
    assert lines == ["1. 小新", "2. 猴哥"]

