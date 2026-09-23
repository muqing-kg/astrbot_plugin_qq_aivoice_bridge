import asyncio
from types import SimpleNamespace

from core.polish import polish_text


class FakeConfig:
    def __init__(self, *, enable_voice_polish=True, polish_llm_provider="prov-1"):
        self.enable_voice_polish = enable_voice_polish
        self.polish_llm_provider = polish_llm_provider
        self.polish_prompt = "改写成口语：{text}"


class FakeContext:
    def __init__(self, reply="", error=None):
        self.reply = reply
        self.error = error
        self.calls = []

    async def get_current_chat_provider_id(self, umo):
        return "current-prov"

    async def llm_generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(completion_text=self.reply)


class FakePlugin:
    def __init__(self, config, context):
        self.config = config
        self.context = context


def _run(config, context, text="晚上好"):
    return asyncio.run(polish_text(FakePlugin(config, context), text, "umo"))


def test_polish_returns_rewritten_text():
    context = FakeContext(reply="晚上好呀，今天咋样？")
    result = _run(FakeConfig(), context, "晚上好，今天如何？")
    assert result == "晚上好呀，今天咋样？"
    assert context.calls[0]["chat_provider_id"] == "prov-1"
    assert context.calls[0]["prompt"] == "改写成口语：晚上好，今天如何？"


def test_polish_uses_current_chat_provider_when_unset():
    context = FakeContext(reply="你好呀")
    _run(FakeConfig(polish_llm_provider=""), context)
    assert context.calls[0]["chat_provider_id"] == "current-prov"


def test_polish_falls_back_when_disabled():
    context = FakeContext(reply="不该被调用")
    result = _run(FakeConfig(enable_voice_polish=False), context, "原文")
    assert result == "原文"
    assert context.calls == []


def test_polish_falls_back_when_model_errors():
    context = FakeContext(error=RuntimeError("boom"))
    assert _run(FakeConfig(), context, "原文") == "原文"


def test_polish_falls_back_when_reply_is_runaway():
    context = FakeContext(reply="啊" * 200)
    assert _run(FakeConfig(), context, "短") == "短"


def test_polish_falls_back_when_reply_is_empty():
    context = FakeContext(reply="")
    assert _run(FakeConfig(), context, "原文") == "原文"


def test_polish_logs_the_rewritten_text(monkeypatch):
    records = []
    monkeypatch.setattr(
        "core.polish.logger",
        SimpleNamespace(
            info=lambda msg, *a: records.append(msg % a if a else msg),
            warning=lambda msg, *a: records.append(msg % a if a else msg),
        ),
    )
    result = _run(FakeConfig(), FakeContext(reply="晚上好呀主人"), "晚上好")

    assert result == "晚上好呀主人"
    assert any("晚上好呀主人" in line for line in records)
    assert any("口播润色完成" in line for line in records)


def test_polish_warns_when_result_is_discarded(monkeypatch):
    records = []
    monkeypatch.setattr(
        "core.polish.logger",
        SimpleNamespace(
            info=lambda msg, *a: records.append(msg % a if a else msg),
            warning=lambda msg, *a: records.append(msg % a if a else msg),
        ),
    )
    result = _run(FakeConfig(), FakeContext(reply=""), "原文")

    assert result == "原文"
    assert any("不可用" in line for line in records)
