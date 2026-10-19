from core.roles import BUILTIN_ROLES, format_role_list, resolve_role


def test_role_resolution_by_number_name_and_id():
    assert resolve_role("1").name == BUILTIN_ROLES[0].name
    assert resolve_role("温柔妹妹").role_id == "lucy-voice-f36"
    assert resolve_role("lucy-voice-f36").name == "温柔妹妹"


def test_role_list_is_numbered():
    lines = format_role_list(BUILTIN_ROLES[:2]).splitlines()
    assert lines == ["1. 小新", "2. 猴哥"]

