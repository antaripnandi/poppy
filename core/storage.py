"""User data paths and atomic writes. Legacy files are copied, never removed."""

import base64
import json
import os
from pathlib import Path

from PySide6.QtCore import QIODevice, QSaveFile


def resource_path(name: str) -> Path:
    return Path(__file__).resolve().parent.parent / name


def data_dir() -> Path:
    override = os.environ.get("POPPY_DATA_DIR")
    if override:
        return Path(override)
    return Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "Poppy"


def atomic_write(path: Path, content: bytes):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    output = QSaveFile(str(path))
    if not output.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(output.errorString())
    if output.write(content) != len(content):
        output.cancelWriting()
        raise OSError(output.errorString())
    if not output.commit():
        raise OSError(output.errorString())


def write_text(path: Path, content: str):
    atomic_write(path, content.encode("utf-8"))


def write_json(path: Path, content):
    write_text(path, json.dumps(content, ensure_ascii=False, indent=2))


def protect_spotify_cookie(cookie: str) -> str:
    if not cookie:
        return ""
    try:
        import win32crypt
        blob = win32crypt.CryptProtectData(cookie.encode("utf-8"), "Poppy Spotify lyrics", None, None, None, 1)
        return base64.b64encode(blob).decode("ascii")
    except Exception:
        raise OSError("Windows could not protect the Spotify cookie.") from None


def spotify_cookie(media: dict) -> str:
    encoded = media.get("spotify_sp_dc_protected")
    if encoded:
        try:
            import win32crypt
            _, value = win32crypt.CryptUnprotectData(base64.b64decode(encoded, validate=True), None, None, None, 1)
            return value.decode("utf-8")
        except Exception:
            return ""
    return media.get("spotify_sp_dc", "") or ""


def data_path(name: str) -> Path:
    path = data_dir() / name
    if not path.exists() and not os.environ.get("POPPY_DATA_DIR"):
        legacy = Path(os.path.expanduser("~/.poppy")) / name
        if legacy.is_file():
            atomic_write(path, legacy.read_bytes())
    return path
