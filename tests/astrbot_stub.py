"""Minimal AstrBot stubs so plugin modules can be imported and driven in tests."""

from __future__ import annotations

import sys
import types
from pathlib import Path


class Plain:
    def __init__(self, text=""):
        self.text = text


class Record:
    def __init__(self, file=""):
        self.file = file

    @staticmethod
    def fromFileSystem(path, **_):
        return Record(file=path)


class File:
    def __init__(self, name="", file="", **_):
        self.name = name
        self.file = file


class MessageChain:
    def __init__(self, chain=None, **_):
        self.chain = chain or []


class Filter:
    class PermissionType:
        ADMIN = "admin"

    def command(self, _name):
        return lambda fn: fn

    def permission_type(self, _kind):
        return lambda fn: fn

    def on_decorating_result(self, *_args, **_kwargs):
        return lambda fn: fn


class Star:
    def __init__(self, context):
        self.context = context


class StarTools:
    @staticmethod
    def get_data_dir():
        return Path.cwd() / "test_data"


class Context:
    pass


def _module(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


_LOGS: list[tuple[str, str]] = []


def install(logs=None):
    """Install the stub ``astrbot`` package and return the recorded log list.

    Must be called before importing any plugin module: ``core.pipeline`` binds
    ``astrbot.api`` at import time.
    """

    recorded: list[tuple[str, str]] = logs if logs is not None else _LOGS

    def make(level):
        def log(msg, *args, **_kwargs):
            recorded.append((level, msg % args if args else msg))

        return log

    logger = types.SimpleNamespace(
        debug=make("DEBUG"),
        info=make("INFO"),
        warning=make("WARN"),
        error=make("ERROR"),
    )

    api = _module("astrbot.api", logger=logger)
    _module("astrbot", api=api)
    _module("astrbot.api.event", filter=Filter(), MessageChain=MessageChain)
    _module(
        "astrbot.api.message_components",
        Plain=Plain,
        Record=Record,
        File=File,
    )
    _module(
        "astrbot.api.star",
        Star=Star,
        StarTools=StarTools,
        Context=Context,
    )
    return recorded
