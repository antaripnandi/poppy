"""User data paths and atomic writes. Legacy files are copied, never removed."""

import json
import os
from pathlib import Path

from PySide6.QtCore import QIODevice, QSaveFile


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


def data_path(name: str) -> Path:
    path = data_dir() / name
    if not path.exists() and not os.environ.get("POPPY_DATA_DIR"):
        legacy = Path(os.path.expanduser("~/.poppy")) / name
        if legacy.is_file():
            atomic_write(path, legacy.read_bytes())
    return path
