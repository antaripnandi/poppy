"""
Poppy UI Styling & Theme System
Directly inspired by NotchX (by Navneet Kaur / Raho Osman) and macOS Dynamic Island.
Features NotchX's 7 theme presets, frosted card styling, and clean sans-serif typography.
"""

THEME_PRESETS = {
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


def get_theme(theme_name: str) -> dict:
    return THEME_PRESETS.get(theme_name, THEME_PRESETS[DEFAULT_THEME])


def get_stylesheet(theme_name: str = DEFAULT_THEME) -> str:
    theme = get_theme(theme_name)
    accent = theme["accent"]

    return f"""
* {{
    font-family: 'Segoe UI Variable Display', 'Segoe UI', -apple-system, BlinkMacSystemFont, 'Inter', system-ui, sans-serif;
    color: #e2e8f0;
    outline: none;
}}

QToolTip {{
    background-color: #0f1219;
    color: #f1f5f9;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 5px;
    padding: 4px 8px;
    font-size: 11px;
}}

QLineEdit {{
    background-color: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 6px;
    padding: 5px 8px;
    color: #f8fafc;
    font-size: 11px;
    selection-background-color: {accent};
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
    font-size: 11px;
    line-height: 1.4;
    selection-background-color: {accent};
}}

QTextEdit:focus {{
    border: 1px solid {accent};
}}

QPushButton {{
    background-color: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 500;
    color: #cbd5e1;
}}

QPushButton:hover {{
    background-color: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.12);
    color: #ffffff;
}}

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
    background: #f8fafc;
    width: 12px;
    margin-top: -4px;
    margin-bottom: -4px;
    border-radius: 6px;
}}

QSlider::handle:horizontal:hover {{
    background: #ffffff;
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
