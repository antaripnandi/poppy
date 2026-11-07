"""Shared-mode application volumes on the default Windows playback output."""

import ctypes
import os
from collections import defaultdict
from contextlib import ExitStack, contextmanager
from ctypes import byref, c_float, c_void_p, wintypes
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from uuid import UUID

import psutil

from poppy.core.system_controls import GUID
from poppy.core.system_features import _windows_com_interface


@dataclass(frozen=True)
class AppVolume:
    name: str
    path: str
    sessions: tuple[str, ...]
    volume: int
    muted: bool
    mixed: bool


def _method(pointer, slot, result, *types):
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(c_void_p))).contents
    return ctypes.WINFUNCTYPE(result, c_void_p, *types)(table[slot])


def _call(pointer, slot, types, *args):
    result = _method(pointer, slot, ctypes.HRESULT, *types)(pointer, *args)
    if result < 0:
        raise OSError(f"Windows audio call failed ({result:#x})")
    return result


def _pointer(stack, owner, slot, types=(), *args):
    pointer = c_void_p()
    _call(owner, slot, (*types, ctypes.POINTER(c_void_p)), *args, byref(pointer))
    if not pointer.value:
        raise OSError("Windows returned an empty audio interface.")
    stack.callback(_method(pointer, 2, wintypes.ULONG), pointer)
    return pointer


def _identity(owner, slot):
    result = c_void_p()
    _call(owner, slot, (ctypes.POINTER(c_void_p),), byref(result))
    if not result.value:
        raise OSError("Windows did not identify the audio object.")
    try:
        return ctypes.wstring_at(result)
    finally:
        free = ctypes.WinDLL("ole32").CoTaskMemFree
        free.argtypes = [c_void_p]
        free.restype = None
        free(result)


@contextmanager
def _sessions(expected_output=None):
    with _windows_com_interface("bcde0395-e52f-467c-8e3d-c4579291692e",
                                "a95664d2-9614-4f35-a746-de8db63617e6") as (enumerator, _):
        with ExitStack() as stack:
            device = _pointer(stack, enumerator, 4, (wintypes.DWORD, wintypes.DWORD), 0, 1)
            output = _identity(device, 5)
            if expected_output is not None and output != expected_output:
                raise OSError("The playback output changed.")
            manager_id = GUID.from_buffer_copy(UUID("77aa99a0-1bd6-484f-8bc7-2c654c9a9b6f").bytes_le)
            manager = _pointer(stack, device, 3, (ctypes.POINTER(GUID), wintypes.DWORD, c_void_p),
                               byref(manager_id), 23, None)
            sessions = _pointer(stack, manager, 5)
            count = ctypes.c_int()
            _call(sessions, 3, (ctypes.POINTER(ctypes.c_int),), byref(count))
            yield output, sessions, count.value


def _session(stack, sessions, index):
    control = _pointer(stack, sessions, 4, (ctypes.c_int,), index)
    control_id = GUID.from_buffer_copy(UUID("bfb7ff88-7239-4fc9-8fa2-07c950be9c6d").bytes_le)
    details = _pointer(stack, control, 0, (ctypes.POINTER(GUID),), byref(control_id))
    state = ctypes.c_int()
    _call(control, 3, (ctypes.POINTER(ctypes.c_int),), byref(state))
    if state.value == 2:  # Expired
        raise OSError("The audio session expired.")
    identity = _identity(details, 13)
    return control, details, identity


def _volume_interface(stack, control):
    volume_id = GUID.from_buffer_copy(UUID("87ce5498-68d6-44e5-9215-6da47ef883d8").bytes_le)
    return _pointer(stack, control, 0, (ctypes.POINTER(GUID),), byref(volume_id))


@lru_cache(maxsize=128)
def _app_name(pid, identity):
    try:
        process = psutil.Process(pid)
        try:
            path = process.exe()
        except psutil.Error:
            path = ""
        return Path(process.name()).stem, path
    except psutil.Error:
        return f"Process {pid}", ""


def read_app_volumes():
    groups = defaultdict(list)
    with _sessions() as (output, sessions, count):
        for index in range(count):
            try:
                with ExitStack() as stack:
                    control, details, identity = _session(stack, sessions, index)
                    if _call(details, 15, ()) == 0:
                        key, name, path = ("system",), "System sounds", ""
                    else:
                        pid = wintypes.DWORD()
                        _call(details, 14, (ctypes.POINTER(wintypes.DWORD),), byref(pid))
                        name, path = _app_name(pid.value, identity)
                        key = ("path", os.path.normcase(path)) if path else ("pid", pid.value)
                    volume = _volume_interface(stack, control)
                    level, muted = c_float(), wintypes.BOOL()
                    _call(volume, 4, (ctypes.POINTER(c_float),), byref(level))
                    _call(volume, 6, (ctypes.POINTER(wintypes.BOOL),), byref(muted))
                    groups[key].append((identity, name, path, round(level.value * 100), bool(muted.value)))
            except OSError:
                continue
    apps = []
    for entries in groups.values():
        ids, names, paths, levels, mutes = zip(*entries)
        apps.append(AppVolume(names[0], paths[0], tuple(sorted(ids)), max(levels), all(mutes),
                              len(set(zip(levels, mutes))) > 1))
    return output, sorted(apps, key=lambda app: (app.name.casefold(), app.sessions))


def set_app_volume(output, identities, *, level=None, muted=None):
    """Apply a gesture only to the output and session instances it started on."""
    with _sessions(output) as (_, sessions, count):
        for index in range(count):
            try:
                with ExitStack() as stack:
                    control, _, identity = _session(stack, sessions, index)
                    if identity not in identities:
                        continue
                    volume = _volume_interface(stack, control)
                    if level is not None:
                        _call(volume, 3, (c_float, c_void_p), min(100, max(0, level)) / 100, None)
                    if muted is not None:
                        _call(volume, 5, (wintypes.BOOL, c_void_p), muted, None)
            except OSError:
                continue
