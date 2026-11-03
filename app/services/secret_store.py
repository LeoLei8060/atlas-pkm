from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from typing import Any

_PREFIX = "dpapi:"


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _protect_windows(value: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buffer = ctypes.create_string_buffer(value)
    source = _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    target = _DataBlob()
    if not crypt32.CryptProtectData(
        ctypes.byref(source), "AtlasPKM", None, None, None, 1, ctypes.byref(target)
    ):
        raise OSError("DPAPI CryptProtectData failed")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(target.pbData)


def _unprotect_windows(value: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buffer = ctypes.create_string_buffer(value)
    source = _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    target = _DataBlob()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)
    ):
        raise OSError("DPAPI CryptUnprotectData failed")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(target.pbData)


def protect(value: str) -> str:
    if not value:
        return ""
    if value.startswith((_PREFIX, "plain:")):
        return value
    if os.name == "nt":
        return _PREFIX + base64.b64encode(_protect_windows(value.encode("utf-8"))).decode("ascii")
    # Linux source mode has no DPAPI; keep a readable fallback so the app still runs.
    return "plain:" + base64.b64encode(value.encode("utf-8")).decode("ascii")


def unprotect(value: str) -> str:
    if not value:
        return ""
    if value.startswith(_PREFIX):
        return _unprotect_windows(base64.b64decode(value[len(_PREFIX):])).decode("utf-8")
    if value.startswith("plain:"):
        return base64.b64decode(value[len("plain:"):]).decode("utf-8")
    return value


def protect_json(value: Any) -> str:
    return protect(json.dumps(value, ensure_ascii=False))


def unprotect_json(value: str, default: Any = None) -> Any:
    try:
        return json.loads(unprotect(value))
    except (ValueError, TypeError, OSError):
        return default
