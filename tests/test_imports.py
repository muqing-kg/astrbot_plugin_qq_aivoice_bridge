import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _module(name):
    mod = ModuleType(name)
    sys.modules[name] = mod
    return mod


def test_plugin_modules_import_with_minimal_astrbot_stubs(monkeypatch):
    astrbot = _module("astrbot")
    api = _module("astrbot.api")
    event_mod = _module("astrbot.api.event")
    components_mod = _module("astrbot.api.message_components")
    star_mod = _module("astrbot.api.star")
    web_mod = _module("astrbot.api.web")

    api.logger = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)

    class Plain:
        def __init__(self, text=""):
            self.text = text

    class Record:
        @staticmethod
        def fromFileSystem(path):
            return {"path": path}

    class File:
        def __init__(self, name, file=""):
            self.name = name
            self.file = file

    class MessageChain:
        def __init__(self, chain=None):
            self.chain = chain or []

    class Filter:
        class PermissionType:
            ADMIN = "admin"

        def command(self, _name):
            return lambda fn: fn

        def permission_type(self, _kind):
            return lambda fn: fn

        def on_decorating_result(self):
            return lambda fn: fn

    filter_obj = Filter()
    event_mod.filter = filter_obj
    event_mod.MessageChain = MessageChain
    components_mod.Plain = Plain
    components_mod.Record = Record
    components_mod.File = File

    class Star:
        def __init__(self, context):
            self.context = context

    class StarTools:
        @staticmethod
        def get_data_dir():
            return Path.cwd() / "test_data"

    class Context:
        pass

    star_mod.Star = Star
    star_mod.StarTools = StarTools
    star_mod.Context = Context
    web_mod.json_response = lambda value: value
    web_mod.error_response = lambda message, status_code=500: {
        "error": message,
        "status": status_code,
    }
    web_mod.request = SimpleNamespace()
    astrbot.api = api

    importlib.invalidate_caches()
    monkeypatch.syspath_prepend(str(Path.cwd().parent))
    module = importlib.import_module("astrbot_plugin_qq_aivoice_bridge.main")
    assert hasattr(module, "QQAIVoiceBridgePlugin")
