from core.segmentation import (
    BUNDLED,
    DROP,
    TEXT_FALLBACK,
    TEXT_FIRST,
    VOICE_ONLY,
    plan_segments,
    resolve_delivery,
    split_text,
)


def test_split_text_respects_max_count():
    parts = split_text("一。二。三。四。", "sentence", 3)
    assert parts == ["一", "二", "三四"]


def test_plan_segments_marks_short_and_blank():
    plans = plan_segments(
        ["ok", "---", "这是一段足够长的测试文本"],
        min_length=5,
        probability=1.0,
        rng=lambda: 0.0,
    )
    assert plans[0].short is True
    assert plans[1].blank is True
    assert plans[2].want_voice is True


def test_delivery_matrix():
    assert resolve_delivery(
        short=False,
        want_voice=True,
        text_enabled=True,
        text_async=False,
        fallback_enabled=True,
    ) == BUNDLED
    assert resolve_delivery(
        short=False,
        want_voice=True,
        text_enabled=True,
        text_async=True,
        fallback_enabled=True,
    ) == TEXT_FIRST
    assert resolve_delivery(
        short=False,
        want_voice=True,
        text_enabled=False,
        text_async=False,
        fallback_enabled=True,
    ) == VOICE_ONLY
    assert resolve_delivery(
        short=False,
        want_voice=False,
        text_enabled=True,
        text_async=False,
        fallback_enabled=True,
    ) == TEXT_FALLBACK
    assert resolve_delivery(
        short=False,
        want_voice=False,
        text_enabled=True,
        text_async=False,
        fallback_enabled=False,
    ) == DROP
    # A segment below the minimum length can never be spoken, so turning the
    # fallback off must not make its wording disappear from the reply.
    assert resolve_delivery(
        short=True,
        want_voice=False,
        text_enabled=True,
        text_async=False,
        fallback_enabled=False,
    ) == TEXT_FALLBACK
