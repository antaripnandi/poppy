"""Appearance context and reversible styling for existing Qt widgets.

Keep the authored dark stylesheet so changing modes never compounds color
conversions. Artwork and user content are left untouched.
"""

import re
from functools import lru_cache
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QWidget

LAYOUT_THEMES = {
    "Classic": {
        "radius": 14, "padding": 16, "spacing": 12, "fill": 0.045,
        "inset": 12, "columns": (1, 1), "home_order": ("clock", "controls", "notes", "shelf"),
        "media_columns": (1, 1), "art_size": 144,
        "description": "Balanced dashboard cards and player beside lyrics.",
    },
    "Minimal": {
        "radius": 4, "padding": 12, "spacing": 8, "fill": 0.0,
        "inset": 6, "columns": (2, 3), "home_order": ("clock", "controls", "notes", "shelf"),
        "media_columns": (2, 3), "art_size": 96,
        "description": "Narrow summary column, flat surfaces and more room for controls and lyrics.",
    },
    "Soft": {
        "radius": 22, "padding": 20, "spacing": 16, "fill": 0.075,
        "inset": 16, "columns": (3, 2), "home_order": ("clock", "notes", "controls", "shelf"),
        "media_columns": (1, 1), "art_size": 160,
        "description": "Notes beside the clock, rounded surfaces and a spacious media player.",
    },
    "Flat": {
        "radius": 2, "padding": 14, "spacing": 12, "fill": 0.0,
        "inset": 12, "columns": (1, 1), "home_order": ("clock", "controls", "notes", "shelf"),
        "media_columns": (2, 3), "art_size": 80,
        "description": "A continuous desktop surface with divider lines, underline tabs and slim controls.",
    },
    "Paper": {
        "radius": 0, "padding": 16, "spacing": 14, "fill": 0.0,
        "inset": 16, "columns": (1, 1), "home_order": ("clock", "controls", "notes", "shelf"),
        "media_columns": (1, 1), "art_size": 80,
        "description": "An open page with a serif clock, quiet headings, plain notes and text-led controls.",
    },
    "Instrument": {
        "radius": 2, "padding": 12, "spacing": 8, "fill": 0.035,
        "inset": 10, "columns": (1, 1), "home_order": ("clock", "controls", "notes", "shelf"),
        "media_columns": (1, 1), "art_size": 128,
        "description": "Compact instrument panels with header strips, numeric readouts and segmented meters.",
    },
}

HOME_CARDS = ("clock", "controls", "notes", "shelf")


def home_order(name, orders=None):
    """Accept only complete permutations, so a bad setting cannot hide a card."""
    default = LAYOUT_THEMES.get(name, LAYOUT_THEMES["Classic"])["home_order"]
    value = orders.get(name) if isinstance(orders, dict) else None
    if (isinstance(value, (list, tuple)) and len(value) == 4
            and all(isinstance(key, str) for key in value) and set(value) == set(HOME_CARDS)):
        return tuple(value)
    return default


def current_layout():
    app = QApplication.instance()
    name = app.property("poppyLayout") if app else "Classic"
    return name if name in LAYOUT_THEMES else "Classic"


def windows_uses_light_theme():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return bool(winreg.QueryValueEx(key, "AppsUseLightTheme")[0])
    except OSError:
        return False


def resolve_light_mode(mode):
    return windows_uses_light_theme() if mode == "System" else mode == "Light"


def is_light_theme():
    app = QApplication.instance()
    return bool(app and app.property("poppyLight"))


def configure_theme(appearance):
    app = QApplication.instance()
    light = resolve_light_mode(appearance.get("mode", "Dark"))
    changed = is_light_theme() != light
    if app.property("poppyLight") != light:
        app.setProperty("poppyLight", light)
    layout = appearance.get("layout", "Classic")
    if app.property("poppyLayout") != layout:
        app.setProperty("poppyLayout", layout)
    return changed


def surface_colors():
    if is_light_theme():
        return {"root": "#f4f1e9" if current_layout() == "Paper" else "#eef1f5", "card": "#ffffff", "text": "#202833", "muted": "#546274"}
    return {"root": "#111419", "card": "#1b2027", "text": "#edf1f7", "muted": "#9ca8b7"}


_COLOR = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|rgba?\([^)]*\)|\b(?:white|black)\b")
_DECLARATION = re.compile(r"([\w-]+)\s*:\s*([^;{}]+)")


def _light_color(value, role, paper=False):
    if role == "selection-background-color":
        return "#365773"
    match = re.fullmatch(r"rgba?\(([^)]+)\)", value)
    alpha = None
    if match:
        parts = [float(part.strip()) for part in match.group(1).split(",")]
        color = QColor(*(int(part) for part in parts[:3]))
        alpha = parts[3] if len(parts) == 4 else None
    else:
        color = QColor(value)
    if not color.isValid():
        return value
    neutral = color.saturation() < 100
    brightness = color.lightness()
    background = "background" in role
    if alpha is not None:
        if neutral:
            shade = 0 if brightness > 128 else 255
            if role == "color" and shade == 0:
                alpha = max(0.62, alpha)
            return f"rgba({shade}, {shade}, {shade}, {alpha})"
        if not background:
            color = color.darker(160)
    elif "border" in role:
        color = QColor("#cbd3de") if neutral else color.darker(145)
    elif background:
        if brightness < 100:
            color = QColor(("#f9f7f1" if paper else "#ffffff") if brightness < 35 else ("#e8e5dd" if paper else "#e2e8f0"))
    elif role == "color":
        if neutral or brightness > 150:
            color = QColor("#202833" if brightness > 175 else "#546274")
        elif brightness > 70:
            color = color.darker(170)
    if alpha is not None:
        return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"
    return color.name()


def themed_stylesheet(source):
    source = _design_stylesheet(source, current_layout())
    if not is_light_theme():
        return source
    return _light_stylesheet(source, current_layout() == "Paper")


@lru_cache(maxsize=1024)
def _design_stylesheet(source, layout):
    """Adapt native controls without losing their authored state/focus selectors."""
    if layout not in ("Flat", "Paper", "Instrument"):
        return source
    radius = LAYOUT_THEMES[layout]["radius"]
    source = re.sub(r"border-radius\s*:\s*[\d.]+px", f"border-radius: {radius}px", source)
    def control(block):
        selector, body = block.groups()
        if "QTextEdit" in selector and ":" not in selector and layout in ("Flat", "Paper"):
            body = re.sub(r"background(?:-color)?\s*:[^;]+;", "background: transparent;", body)
            body = re.sub(r"border\s*:[^;]+;", "border: none;", body)
        if selector.strip() == "QPushButton":
            if layout == "Paper":
                body = re.sub(r"background(?:-color)?\s*:[^;]+;", "background: transparent;", body)
                body = re.sub(r"border\s*:[^;]+;", "border: none;", body)
            elif layout == "Instrument":
                body = re.sub(r"border\s*:[^;]+;", "border: 1px solid rgba(255,255,255,0.18);", body)
        if "QSlider::groove:horizontal" in selector:
            body = re.sub(r"height\s*:[^;]+;", f"height: {8 if layout == 'Instrument' else 2}px;", body)
        elif "QSlider::handle:horizontal" in selector:
            body = re.sub(r"width\s*:[^;]+;", f"width: {2 if layout == 'Instrument' else 8}px;", body)
        return selector + "{" + body + "}"
    source = re.sub(r"([^{}]+)\{([^{}]*)\}", control, source)
    return source


@lru_cache(maxsize=1024)
def _light_stylesheet(source, paper=False):
    def declaration(match):
        role, value = match.groups()
        if role == "color" or "background" in role or role.startswith("border"):
            value = _COLOR.sub(lambda color: _light_color(color.group(), role, paper), value)
        return f"{role}: {value}"
    # Compile declarations only. Qt's ::subcontrol and :hover selectors also
    # contain colons and must retain their exact spelling.
    if "{" not in source:
        return _DECLARATION.sub(declaration, source)
    return re.sub(r"(?<=\{)[^{}]*(?=\})", lambda block: _DECLARATION.sub(declaration, block.group()), source)


def set_widget_style(widget, source):
    if widget.property("poppyStyleSource") != source:
        widget.setProperty("poppyStyleSource", source)
    rendered = themed_stylesheet(source)
    if widget.styleSheet() != rendered:
        widget.setStyleSheet(rendered)


def refresh_theme():
    app = QApplication.instance()
    for widget in [app, *app.allWidgets()]:
        source = widget.property("poppyStyleSource")
        if source is not None:
            rendered = themed_stylesheet(source)
            if widget.styleSheet() != rendered:
                widget.setStyleSheet(rendered)
        if isinstance(widget, QWidget):
            widget.update()
