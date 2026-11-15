import pytest

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from poppy.ui.drawer_tools import DrawerToolButton


@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5, 2.0])
def test_footer_icons_have_centered_visible_strokes(audit_app, scale):
    for name in ("shield", "pencil", "popout", "pin", "awake"):
        button = DrawerToolButton(name, name)
        size = round(button.width() * scale)
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(scale)
        image.fill(Qt.GlobalColor.transparent)
        button.render(image, QPoint(), renderFlags=QWidget.RenderFlag.DrawChildren)
        pixels = [(x, y) for x in range(size) for y in range(size) if image.pixelColor(x, y).alpha() > 128]
        xs, ys = zip(*pixels)
        assert len(pixels) >= 28 * scale * scale
        for points in (xs, ys):
            assert min(points) > 3 * scale and max(points) < size - 3 * scale
            assert abs((min(points) + max(points)) / 2 - (size - 1) / 2) <= scale


def test_footer_toggle_only_changes_after_action_confirms(audit_app):
    button = DrawerToolButton("shield", "Hide from screen capture", toggle=True)
    button.show()
    button.clicked.connect(lambda: button.setChecked(True))
    QTest.keyClick(button, Qt.Key.Key_Space)
    assert button.isChecked()
    button.click()
    assert button.isChecked() and button.accessibleName() == "Hide from screen capture"
