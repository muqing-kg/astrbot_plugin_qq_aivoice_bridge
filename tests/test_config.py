from core.config import ConfigManager


def test_nested_config_is_flattened():
    cfg = ConfigManager(
        {
            "basic": {"relay_group": "123", "default_role": "lucy-voice-daji"},
            "output_settings": {"probability": 0.35},
        }
    )
    assert cfg.relay_group == "123"
    assert cfg.default_role == "lucy-voice-daji"
    assert cfg.probability == 0.35
    assert cfg.send_text_with_tts is False


def test_empty_platforms_means_all_qq_and_clamps_probability():
    cfg = ConfigManager({"basic": {"qq_platforms": []}, "output_settings": {"probability": 9}})
    assert cfg.qq_platforms == []
    assert cfg.probability == 1.0


def test_set_mutates_raw_nested_config():
    raw = {"basic": {"qq_platforms": []}}
    cfg = ConfigManager(raw)
    cfg.set("qq_platforms", ["qq-main"])
    assert raw["basic"]["qq_platforms"] == ["qq-main"]

