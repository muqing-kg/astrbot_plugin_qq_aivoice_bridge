"""Delivery-path tests for ``VoicePipeline``."""

from __future__ import annotations

import asyncio

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
    def get_cached_roles(self, *_args):
        return [ROLE]

    def set_cached_roles(self, *_args):
        return None

    def get_group_role(self, *_args):
        return ""


class FakeQQ:
    def __init__(self, *, native=False, generate_fails=False):
        self.native = native
        self.generate_fails = generate_fails
        self.spoken = []

    def is_configured_qq(self, _platform_id):
        return True

    def resolve_route(self, _event):
        return QQRoute(object(), "qq-main", "10086", native=self.native)

    async def list_characters(self, _bot, _group_id):
        return [ROLE]

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
