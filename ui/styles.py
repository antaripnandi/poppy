"""
Poppy UI Styling & Theme System
Directly inspired by NotchX (by Navneet Kaur / Raho Osman) and macOS Dynamic Island.
Features NotchX's 7 theme presets, frosted card styling, and clean sans-serif typography.
"""

from PySide6.QtGui import QColor
from poppy.ui.theme import DESIGN_PALETTES, LAYOUT_THEMES, home_order


THEME_PRESETS = {
    "Charcoal": {
        "name": "Charcoal", "bg": "#1a1d1e", "gradient": "#1a1d1e",
        "accent": "#b5c9bd", "desc": "Neutral dark gray",
    },
    "Sage": {
        "name": "Sage", "bg": "#17201b", "gradient": "#17201b",
        "accent": "#9db7a6", "desc": "Muted green",
    },
    "Slate": {
        "name": "Slate", "bg": "#191e23", "gradient": "#191e23",
        "accent": "#a8bbc7", "desc": "Muted blue gray",
    },
    "Graphite": {
        "name": "Graphite",
        "bg": "#141418",
        "gradient": "#202028",
        "accent": "#0a84ff",
        "desc": "Deep grey glass with a blue accent",
    },
    "Midnight": {
        "name": "Midnight",
        "bg": "#0a0e1c",
        "gradient": "#182040",
        "accent": "#6e9bff",
        "desc": "Inky navy fading to indigo",
    },
    "Aurora": {
        "name": "Aurora",
        "bg": "#0c1717",
        "gradient": "#241534",
        "accent": "#3ddc97",
        "desc": "Teal-black into violet, with mint",
    },
    "Ember": {
        "name": "Ember",
        "bg": "#181110",
        "gradient": "#2b1610",
        "accent": "#ff9f0a",
        "desc": "Warm charcoal with an amber glow",
    },
    "Lime": {
        "name": "Lime",
        "bg": "#111211",
        "gradient": "#1b1f12",
        "accent": "#b4e61e",
        "desc": "Near-black with a lime accent",
    },
    "Rose": {
        "name": "Rose",
        "bg": "#161012",
        "gradient": "#2a1420",
        "accent": "#ff6b9a",
        "desc": "Dark plum with a rose accent",
    },
    "Pure black": {
        "name": "Pure black",
        "bg": "#000000",
        "gradient": "#000000",
        "accent": "#0a84ff",
        "desc": "The original flat black",
    },
}

DEFAULT_THEME = "Pure black"
DEFAULT_PANEL_WIDTH = 1120
DEFAULT_PANEL_HEIGHT = 500
APPEARANCE_LAYOUT_VERSION = 4


def normalize_appearance(appearance: dict) -> dict:
    """Adopt compact defaults once, preserving explicitly customized dimensions."""
    result = dict(appearance)
    version = result.get("layout_version", 1)
    size = (result.get("open_width"), result.get("open_height"))
    legacy_default = version < 3 and size in ((600, 400), (960, 480))
    if version < APPEARANCE_LAYOUT_VERSION and (legacy_default or size == (960, 560)):
        result.update(open_width=DEFAULT_PANEL_WIDTH, open_height=DEFAULT_PANEL_HEIGHT)
    result.setdefault("open_width", DEFAULT_PANEL_WIDTH)
    result.setdefault("open_height", DEFAULT_PANEL_HEIGHT)
    result.setdefault("layout", "Classic")
    if not isinstance(result["layout"], str) or result["layout"] not in LAYOUT_THEMES:
        result["layout"] = "Classic"
    orders = result.get("home_orders", {})
    result["home_orders"] = {name: list(home_order(name, orders)) for name in LAYOUT_THEMES
                             if isinstance(orders, dict) and name in orders}
    result.setdefault("mode", "Dark")
    if result.get("peek_color_source") not in ("artwork", "fixed", "theme"):
        result["peek_color_source"] = "artwork"
    color = result.get("peek_color")
    result["peek_color"] = QColor(color).name() if isinstance(color, str) and QColor(color).isValid() else "#242f4a"
    result["layout_version"] = APPEARANCE_LAYOUT_VERSION
    return result



def get_theme(theme_name: str, layout="Classic") -> dict:
    palette = THEME_PRESETS.get(theme_name if isinstance(theme_name, str) else DEFAULT_THEME, THEME_PRESETS[DEFAULT_THEME])
    if isinstance(layout, str) and layout in DESIGN_PALETTES:
        root, card, _, _, accent = DESIGN_PALETTES[layout][0]
        return {**palette, "bg": root, "gradient": card if layout == "Deck" else root,
                "accent": accent if palette["name"] == DEFAULT_THEME else palette["accent"]}
    return palette


def get_stylesheet(theme_name: str = DEFAULT_THEME, layout="Classic") -> str:
    theme = get_theme(theme_name, layout)
    accent = theme["accent"]

    return f"""
* {{
    font-family: 'Segoe UI';
    color: #e2e8f0;
    font-size: 12px;
}}

QMenu {{ background: #202223; border: 1px solid #3a3d3e; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 7px 26px 7px 10px; border-radius: 5px; }}
QMenu::item:selected {{ background: #343738; }}
QMenu::item:disabled {{ color: #818687; }}
QMenu::separator {{ height: 1px; background: #3a3d3e; margin: 5px; }}
QDialog, QMessageBox {{ background: #1b2027; }}

QToolTip {{
    background-color: #0f1219;
    color: #f1f5f9;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 5px;
    padding: 4px 8px;
    font-size: 12px;
}}

QLineEdit {{
    background-color: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 6px;
    padding: 5px 8px;
    color: #f8fafc;
    font-size: 12px;
    selection-background-color: {accent};
    selection-color: #ffffff;
}}

QLineEdit:focus {{
    border: 1px solid {accent};
    background-color: rgba(255, 255, 255, 0.07);
}}

QTextEdit {{
    background-color: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 6px;
    padding: 6px;
    color: #f1f5f9;
    font-size: 12px;
    selection-background-color: {accent};
    selection-color: #ffffff;
}}

QTextEdit:focus {{
    border: 1px solid {accent};
}}

QPushButton {{
    background-color: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 12px;
    font-weight: 500;
    color: #cbd5e1;
}}

QPushButton:hover {{
    background-color: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.12);
    color: #ffffff;
}}

QPushButton:focus {{ border: 1px solid #b5babe; }}
QPushButton:disabled {{ color: #727779; background: rgba(255,255,255,0.025); }}

QPushButton:pressed {{
    background-color: rgba(255, 255, 255, 0.18);
}}

QSlider::groove:horizontal {{
    height: 4px;
    background: rgba(255, 255, 255, 0.12);
    border-radius: 2px;
}}

QSlider::sub-page:horizontal {{
    background: {accent};
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    background: #7f8b91;
    width: 12px;
    margin-top: -4px;
    margin-bottom: -4px;
    border-radius: 6px;
}}

QSlider::handle:horizontal:hover {{
    background: #647982;
}}

QScrollBar:vertical {{
    border: none;
    background: transparent;
    width: 4px;
    margin: 0px;
}}

QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 0.15);
    min-height: 20px;
    border-radius: 2px;
}}

QScrollBar::handle:vertical:hover {{
    background: rgba(255, 255, 255, 0.3);
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
"""
