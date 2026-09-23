"""Delivery-path tests for ``VoicePipeline``."""

from __future__ import annotations

import asyncio
from pathlib import Path

from tests.astrbot_stub import Plain, install

install()

from core import pipeline as pipeline_mod
from core.audio import AudioConverter
from core.qq_voice import QQRoute
from core.roles import Role

ROLE = Role("lucy-voice-f36", "温柔妹妹")
ORIGINAL = "第一句话。第二句话。"
POLISHED = "润色一。润色二。"


class FakeConfig:
    enabled = True
    auto_tts = True
    probability = 1.0
    min_text_length = 1
    max_text_length = 500
    send_text_with_tts = True
    send_text_async = False
    enable_segmentation = False
    segment_pattern = "sentence"
    segment_max_count = 10
    segment_voice_probability = 1.0
    segment_text_fallback = True
    enable_voice_polish = False
    display_polished_text = False
    audio_format = "wav"
    default_role = "lucy-voice-f36"
    max_concurrency = 2


class FakeState:
    def __init__(self, roles=(ROLE,)):
        self.roles = list(roles)

    def get_cached_roles(self, *_args):
        return list(self.roles)

    def set_cached_roles(self, *_args):
        return None

    def get_group_role(self, *_args):
        return ""


class FakeQQ:
    def __init__(self, *, native=False, generate_fails=False, roles=(ROLE,)):
        self.native = native
        self.generate_fails = generate_fails
        self.roles = list(roles)
        self.spoken = []

    def is_configured_qq(self, _platform_id):
        return True

    def resolve_route(self, _event):
        return QQRoute(object(), "qq-main", "10086", native=self.native)

    async def list_characters(self, _bot, _group_id):
        return list(self.roles)

    async def get_ai_record(self, _bot, _group_id, _role_id, text):
        if self.generate_fails:
            raise RuntimeError("qq down")
        self.spoken.append(text)
        return "https://example.invalid/a.silk"

    async def download(self, _url):
        raise RuntimeError("no download in tests")


class FakePlugin:
    def __init__(self, config, state):
        self.config = config
        self.state = state
        self.context = None


class FakeResult:
    def __init__(self, text):
        self.chain = [Plain(text)]

    def is_llm_result(self):
        return True


class FakeEvent:
    def __init__(self, text=ORIGINAL):
        self._result = FakeResult(text)
        self.texts: list[str] = []

    def get_result(self):
        return self._result

    @property
    def unified_msg_origin(self):
        return "telegram:FriendMessage:1"

    def get_platform_name(self):
        return "telegram"

    def get_platform_id(self):
        return "tg-main"

    def get_group_id(self):
        return ""

    async def send(self, chain):
        self.texts.extend(seg.text for seg in chain.chain if isinstance(seg, Plain))


def _build(monkeypatch, tmp_path, config, qq, *, send_impl=None):
    pipeline = pipeline_mod.VoicePipeline(
        FakePlugin(config, FakeState()), qq, AudioConverter(tmp_path / "temp")
    )
    if send_impl is not None:
        monkeypatch.setattr(pipeline, "_send_audio", send_impl)
    return pipeline


async def _drain(pipeline):
    for _ in range(50):
        pending = getattr(pipeline, "_pending_tasks", None)
        if not pending:
            return
        await asyncio.sleep(0.01)


def test_segment_failure_does_not_repeat_text(monkeypatch, tmp_path):
    """TEXT_FIRST already sent the segment; the failure fallback must not resend."""
    config = FakeConfig()
    config.enable_segmentation = True
    config.send_text_async = True
    qq = FakeQQ(native=True, generate_fails=True)
    pipeline = _build(monkeypatch, tmp_path, config, qq)
    event = FakeEvent()

    asyncio.run(pipeline.handle_decorating_result(event))

    assert event.texts == ["第一句话", "第二句话"], event.texts


def test_async_audio_failure_falls_back_to_text(monkeypatch, tmp_path):
    """Voice-only async mode must not swallow the reply when the send fails."""
    config = FakeConfig()
    config.send_text_with_tts = False
    config.send_text_async = True

    async def failing_send(_event, _path, _text):
        raise RuntimeError("platform refused")

    qq = FakeQQ()
    pipeline = _build(monkeypatch, tmp_path, config, qq, send_impl=failing_send)

    async def fake_generate(_route, _role, _text):
        path = tmp_path / "voice.wav"
        path.write_bytes(b"RIFF....WAVEfmt ")
        return path

    monkeypatch.setattr(pipeline, "_generate_file", fake_generate)
    event = FakeEvent()

    async def scenario():
        await pipeline.handle_decorating_result(event)
        await _drain(pipeline)

    asyncio.run(scenario())

    assert event.texts == [ORIGINAL], event.texts


def test_segment_display_honours_original_text(monkeypatch, tmp_path):
    """display_polished_text=False must show the original wording, even segmented."""
    config = FakeConfig()
    config.enable_segmentation = True
    config.enable_voice_polish = True

    async def fake_polish(_plugin, _text, _uid):
        return POLISHED

    monkeypatch.setattr(pipeline_mod, "polish_text", fake_polish)
    qq = FakeQQ()
    pipeline = _build(monkeypatch, tmp_path, config, qq)
    event = FakeEvent()

    asyncio.run(pipeline.handle_decorating_result(event))

    assert event.texts == ["第一句话", "第二句话"], event.texts
    assert qq.spoken == ["润色一", "润色二"], qq.spoken


def test_polish_changing_sentence_count_shows_text_in_full(monkeypatch, tmp_path):
    """A rewritten sentence count must not misalign or drop the shown text."""
    config = FakeConfig()
    config.enable_segmentation = True
    config.enable_voice_polish = True
    spoken: list[str] = []

    async def fake_polish(_plugin, _text, _uid):
        return "润色一。润色二。润色三。"

    async def fake_generate(_route, _role, text):
        spoken.append(text)
        path = tmp_path / "voice.wav"
        path.write_bytes(b"RIFF....WAVEfmt ")
        return path

    monkeypatch.setattr(pipeline_mod, "polish_text", fake_polish)
    qq = FakeQQ()
    pipeline = _build(monkeypatch, tmp_path, config, qq)
    monkeypatch.setattr(pipeline, "_generate_file", fake_generate)
    event = FakeEvent()

    asyncio.run(pipeline.handle_decorating_result(event))

    assert event.texts == [ORIGINAL], event.texts
    assert spoken == ["润色一", "润色二", "润色三"], spoken


def test_local_send_failure_falls_back_to_text(monkeypatch, tmp_path):
    """A failing local send must resend the text instead of raising."""
    config = FakeConfig()
    config.send_text_with_tts = False
    path = tmp_path / "voice.wav"

    async def fake_generate(_route, _role, _text):
        path.write_bytes(b"RIFF....WAVEfmt ")
        return path

    async def failing_send(_event, _path, _text):
        raise RuntimeError("platform refused")

    qq = FakeQQ()
    pipeline = _build(monkeypatch, tmp_path, config, qq)
    monkeypatch.setattr(pipeline, "_generate_file", fake_generate)
    monkeypatch.setattr(pipeline, "_send_audio", failing_send)
    event = FakeEvent()

    asyncio.run(pipeline.handle_decorating_result(event))

    assert event.texts == [ORIGINAL], event.texts
    assert not path.exists()


def test_async_text_is_not_repeated_with_the_voice(monkeypatch, tmp_path):
    """Async text plus sync text must show the text exactly once."""
    config = FakeConfig()
    config.send_text_async = True
    config.send_text_with_tts = True

    async def fake_generate(_route, _role, _text):
        path = tmp_path / "voice.wav"
        path.write_bytes(b"RIFF....WAVEfmt ")
        return path

    qq = FakeQQ()
    pipeline = _build(monkeypatch, tmp_path, config, qq)
    monkeypatch.setattr(pipeline, "_generate_file", fake_generate)
    event = FakeEvent()

    async def scenario():
        await pipeline.handle_decorating_result(event)
        await _drain(pipeline)

    asyncio.run(scenario())

    assert event.texts == [ORIGINAL], event.texts


def test_shutdown_waits_for_a_pending_send(monkeypatch, tmp_path):
    """A send that finishes inside the grace period must not be cancelled."""
    pipeline = _build(monkeypatch, tmp_path, FakeConfig(), FakeQQ())
    ran: list[str] = []

    async def quick():
        await asyncio.sleep(0.01)
        ran.append("done")

    async def scenario():
        pipeline._track(asyncio.create_task(quick()))
        await pipeline.shutdown(grace=1.0)

    asyncio.run(scenario())

    assert ran == ["done"]
    assert pipeline._pending_tasks == set()


def test_shutdown_cancels_a_stuck_send(monkeypatch, tmp_path):
    """A send that outlives the grace period must be cancelled, not leaked."""
    pipeline = _build(monkeypatch, tmp_path, FakeConfig(), FakeQQ())
    seen: list[str] = []

    async def never_finishes():
        try:
            await asyncio.sleep(3600)
        finally:
            seen.append("cancelled")

    async def scenario():
        task = asyncio.create_task(never_finishes())
        pipeline._track(task)
        await pipeline.shutdown(grace=0.05)
        return task

    task = asyncio.run(scenario())

    assert task.cancelled()
    assert seen == ["cancelled"]
    assert pipeline._pending_tasks == set()


def test_segment_async_voice_is_sent_in_the_background(monkeypatch, tmp_path):
    """TEXT_FIRST segments queue the voice and hand the temp file to the task."""
    config = FakeConfig()
    config.enable_segmentation = True
    config.send_text_async = True
    paths: list[Path] = []
    sent: list[str] = []

    async def fake_generate(_route, _role, _text):
        path = tmp_path / f"voice{len(paths)}.wav"
        path.write_bytes(b"RIFF....WAVEfmt ")
        paths.append(path)
        return path

    async def fake_send(_event, path, text):
        assert Path(path).exists()
        sent.append(text)

    qq = FakeQQ()
    pipeline = _build(monkeypatch, tmp_path, config, qq)
    monkeypatch.setattr(pipeline, "_generate_file", fake_generate)
    monkeypatch.setattr(pipeline, "_send_audio", fake_send)
    event = FakeEvent()

    async def scenario():
        await pipeline.handle_decorating_result(event)
        await _drain(pipeline)

    asyncio.run(scenario())

    assert event.texts == ["第一句话", "第二句话"], event.texts
    # The text already went out per segment, so the voice carries no repeat.
    assert sent == ["", ""], sent
    assert [path for path in paths if path.exists()] == []


def test_segments_without_a_role_still_send_text(monkeypatch, tmp_path):
    """No role anywhere means no voice, but the reply must not vanish either."""
    config = FakeConfig()
    config.enable_segmentation = True
    config.send_text_with_tts = False
    config.segment_text_fallback = False
    qq = FakeQQ(roles=())
    pipeline = _build(monkeypatch, tmp_path, config, qq)
    pipeline.plugin.state = FakeState(roles=())
    event = FakeEvent()

    asyncio.run(pipeline.handle_decorating_result(event))

    assert event.texts == ["第一句话", "第二句话"], event.texts
