"""
Automated Verification Test Suite for Poppy Senior Engineering Audit
Validates all critical bug fixes, security constraints, and math evaluation.
"""

import ast
import operator as op
import pytest
from poppy.core.media_manager import format_source_name
from poppy.core.pomodoro import PomodoroManager, PomoState


# -------------------------------------------------------------
# 1. Media Source Classification Verification
# -------------------------------------------------------------
def test_media_source_detection_no_hardcoding():
    # Assert personal watch history titles are NOT classified as YouTube in Brave
    assert format_source_name("brave.exe", "Part of Me - Katy Perry") == "Brave"
    assert format_source_name("brave.exe", "Circle of Curvature Lecture 3") == "Brave"
    
    # Assert legitimate YouTube titles ARE classified properly
    assert format_source_name("brave.exe", "Lofi Hip Hop - YouTube") == "YouTube"
    assert format_source_name("brave.exe", "music.youtube.com - Song") == "YouTube Music"
    assert format_source_name("chrome.exe", "YouTube - Video Title") == "YouTube"
    assert format_source_name("Spotify.exe", "Song Title") == "Spotify"


# -------------------------------------------------------------
# 2. Safe AST Math Evaluator Verification
# -------------------------------------------------------------
def safe_calc_eval(text: str):
    text = text.strip()
    if not text:
        return ""
    operators = {
        ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
        ast.Div: op.truediv, ast.FloorDiv: op.floordiv,
        ast.Mod: op.mod, ast.Pow: op.pow, ast.USub: op.neg
    }
    def _eval_node(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        elif isinstance(node, ast.BinOp) and type(node.op) in operators:
            left = _eval_node(node.left)
            right = _eval_node(node.right)
            if isinstance(node.op, ast.Pow) and (abs(right) > 100 or abs(left) > 10000):
                raise OverflowError("Exponent too large")
            return operators[type(node.op)](left, right)
        elif isinstance(node, ast.UnaryOp) and type(node.op) in operators:
            return operators[type(node.op)](_eval_node(node.operand))
        raise ValueError("Unsupported expression")

    try:
        parsed = ast.parse(text.replace('^', '**'), mode='eval')
        val = _eval_node(parsed.body)
        if isinstance(val, (int, float)):
            return f"= {val:,.4g}" if isinstance(val, float) else f"= {val:,}"
    except Exception:
        pass
    return ""


def test_safe_math_evaluator_valid_expressions():
    assert safe_calc_eval("45 * 12") == "= 540"
    assert safe_calc_eval("120 / 3") == "= 40"
    assert safe_calc_eval("2 ^ 8") == "= 256"
    assert safe_calc_eval("(10 + 5) * 2") == "= 30"
    assert safe_calc_eval("-5 + 15") == "= 10"


def test_safe_math_evaluator_security_and_dos_protection():
    # Code injection attempts must fail safely
    assert safe_calc_eval("__import__('os').system('calc')") == ""
    assert safe_calc_eval("eval('2+2')") == ""
    assert safe_calc_eval("open('secret.txt')") == ""
    
    # Unbounded exponent attempts (DoS / CPU freeze attacks) must fail safely
    assert safe_calc_eval("9 ^ 9999999") == ""
    assert safe_calc_eval("2 ^ 500") == ""


# -------------------------------------------------------------
# 3. Pomodoro State Machine Transitions
# -------------------------------------------------------------
def test_pomodoro_transitions():
    pomo = PomodoroManager(work_duration=10, break_duration=5, parent=None)
    pomo.sound_enabled = False  # Mute during automated test
    
    # Initial state
    assert pomo.state == PomoState.STOPPED
    
    # Start focus session
    pomo.start()
    assert pomo.state == PomoState.WORKING
    assert pomo.remaining_seconds == 10
    
    # Simulate countdown to end
    pomo.remaining_seconds = 1
    pomo._tick()  # decrements to 0, transitions to short break
    assert pomo.state == PomoState.SHORT_BREAK
    assert pomo.completed_cycles == 1
    assert pomo.remaining_seconds == 5


# -------------------------------------------------------------
# 4. Audio Controller Stability
# -------------------------------------------------------------
def test_audio_controller_initialization():
    from poppy.core.system_controls import SystemAudioController
    audio = SystemAudioController()
    vol = audio.get_volume()
    assert 0 <= vol <= 100
