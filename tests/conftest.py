"""Make the plugin importable from pytest, with or without a real AstrBot."""

from __future__ import annotations

import importlib
import sys
import types
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _Logger:
    def _ignore(self, *args, **kwargs):
        return None

    debug = info = warning = error = exception = _ignore


class _Component:
    def __init__(self, **fields):
        self.__dict__.update(fields)


class Plain(_Component):
    def __init__(self, text):
        super().__init__(text=text)


class At(_Component):
    pass


class File(_Component):
    def __init__(self, name, file="", url=""):
        super().__init__(name=name, file_=file, url=url)


class _Media(_Component):
    @classmethod
    def fromURL(cls, url):
        return cls(file=url)

    @classmethod
    def fromFileSystem(cls, path):
        return cls(file=f"file:///{path}", path=path)


class Image(_Media):
    pass


class Video(_Media):
    pass


class Record(_Media):
    pass


class Star:
    def __init__(self, context, config=None):
        self.context = context


class EventMessageType(Enum):
    ALL = "all"


def _module(name: str, **attributes) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    module.__path__ = []
    sys.modules[name] = module
    return module


def _install_astrbot_stubs() -> None:
    try:
        importlib.import_module("astrbot.api.web")
        importlib.import_module("astrbot.api.message_components")
    except ImportError:
        pass
    else:
        return
    _module("astrbot")
    _module("astrbot.api", logger=_Logger())
    _module(
        "astrbot.api.web",
        request=SimpleNamespace(username=None, query={}),
        json_response=lambda payload: payload,
        error_response=lambda message, status_code=400: SimpleNamespace(status_code=status_code, message=message),
    )
    _module("astrbot.api.star", Context=object, Star=Star, StarTools=SimpleNamespace(), register=lambda **_: lambda cls: cls)
    _module("astrbot.api.event")
    _module(
        "astrbot.api.event.filter",
        EventMessageType=EventMessageType,
        event_message_type=lambda _: lambda function: function,
    )
    _module("astrbot.api.message_components", At=At, File=File, Image=Image, Plain=Plain, Record=Record, Video=Video)


_install_astrbot_stubs()
