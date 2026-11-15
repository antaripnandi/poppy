"""Application-local fonts for the compact pill."""

import hashlib
import io
import re
from pathlib import Path
from zipfile import ZipFile

from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics

from poppy.core.storage import atomic_write, data_path, resource_path


DEFAULT_PILL_FONT = "Rubik Spray Paint"
SYSTEM_PILL_FONT = "Segoe UI"
PILL_FONT_RESOURCE = "assets/fonts/RubikSprayPaint-Regular.ttf"
PILL_FONT_LICENSE = "assets/fonts/RubikSprayPaint-OFL.txt"
MAX_FONT_BYTES = 16 * 1024 * 1024
_loaded_fonts = {}


def pill_font_path(selection):
    if selection == DEFAULT_PILL_FONT:
        return resource_path(PILL_FONT_RESOURCE)
    if re.fullmatch(r"[a-f0-9]{64}\.(?:otf|ttf)", selection):
        return data_path("pill-fonts") / selection
    return None


def _font_family(path):
    if path in _loaded_fonts:
        return _loaded_fonts[path]
    if not path.is_file():
        return ""
    font_id = QFontDatabase.addApplicationFont(str(path))
    families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
    if families:
        _loaded_fonts[path] = families[0]
        return families[0]
    return ""


def pill_font_family(selection):
    path = pill_font_path(selection)
    if path is not None:
        return _font_family(path) or SYSTEM_PILL_FONT
    return selection if QFontDatabase.hasFamily(selection) else SYSTEM_PILL_FONT


def pill_text_font(selection, size, height, width):
    family = pill_font_family(selection)
    font = QFont(family)
    font.setWeight(QFont.Weight.DemiBold if family == SYSTEM_PILL_FONT else QFont.Weight.Normal)
    font.setPixelSize(size)
    while font.pixelSize() > 8:
        metrics = QFontMetrics(font)
        text_width = metrics.horizontalAdvance("12:00 PM") + metrics.horizontalAdvance("00:00")
        if metrics.height() <= height - 4 and text_width <= width:
            break
        font.setPixelSize(font.pixelSize() - 1)
    return font


def import_pill_font(source: Path):
    suffix = source.suffix.lower()
    with source.open("rb") as file:
        data = file.read(MAX_FONT_BYTES + 1)
    if (suffix not in (".ttf", ".otf") or len(data) > MAX_FONT_BYTES
            or data[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true")):
        raise ValueError("Choose a valid TTF or OTF font under 16 MB.")
    selection = hashlib.sha256(data).hexdigest() + suffix
    path = pill_font_path(selection)
    if path not in _loaded_fonts or not path.is_file():
        font_id = QFontDatabase.addApplicationFontFromData(data)
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        if not families:
            if font_id >= 0:
                QFontDatabase.removeApplicationFont(font_id)
            raise ValueError("Qt could not read this font.")
        try:
            atomic_write(path, data)
        except OSError:
            QFontDatabase.removeApplicationFont(font_id)
            raise
        _loaded_fonts[path] = families[0]
    return selection


def export_pill_font(selection, destination):
    source = pill_font_path(selection)
    if source is None:
        raise ValueError("Choose a bundled or imported font to export.")
    if selection == DEFAULT_PILL_FONT:
        output = io.BytesIO()
        with ZipFile(output, "w") as archive:
            archive.write(source, source.name)
            archive.write(resource_path(PILL_FONT_LICENSE), "OFL.txt")
        atomic_write(destination, output.getvalue())
    else:
        atomic_write(destination, source.read_bytes())
