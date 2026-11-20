"""Small vector buttons for the drawer footer."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QPushButton, QStyle, QStyleOptionButton

from poppy.ui.theme import is_light_theme, surface_colors


def _tool_path(name):
    path = QPainterPath()
    if name == "shield":
        path.moveTo(8, 1.5)
        path.lineTo(13.5, 3.8)
        path.lineTo(13.5, 7.4)
        path.cubicTo(13.5, 10.7, 11.2, 13.1, 8, 14.5)
        path.cubicTo(4.8, 13.1, 2.5, 10.7, 2.5, 7.4)
        path.lineTo(2.5, 3.8)
        path.closeSubpath()
    elif name == "pencil":
        path.moveTo(2, 14)
        path.lineTo(3.2, 10)
        path.lineTo(10.6, 2.6)
        path.quadTo(11.4, 1.8, 12.2, 2.6)
        path.lineTo(13.4, 3.8)
        path.quadTo(14.2, 4.6, 13.4, 5.4)
        path.lineTo(6, 12.8)
        path.closeSubpath()
        path.moveTo(9.4, 3.8)
        path.lineTo(12.2, 6.6)
    elif name == "popout":
        path.moveTo(7.5, 3)
        path.lineTo(3.5, 3)
        path.quadTo(2, 3, 2, 4.5)
        path.lineTo(2, 12.5)
        path.quadTo(2, 14, 3.5, 14)
        path.lineTo(11.5, 14)
        path.quadTo(13, 14, 13, 12.5)
        path.lineTo(13, 8.5)
        path.moveTo(8, 8)
        path.lineTo(14, 2)
        path.moveTo(10, 2)
        path.lineTo(14, 2)
        path.lineTo(14, 6)
    elif name == "pin":
        path.moveTo(9, 1.8)
        path.lineTo(14.2, 7)
        path.lineTo(12.2, 7.5)
        path.lineTo(10.2, 9.5)
        path.lineTo(10.1, 11.9)
        path.lineTo(4.1, 5.9)
        path.lineTo(6.5, 5.8)
        path.lineTo(8.5, 3.8)
        path.closeSubpath()
        path.moveTo(7.1, 8.9)
        path.lineTo(2.1, 13.9)
    elif name == "awake":
        path.moveTo(2, 4.5)
        path.lineTo(11, 4.5)
        path.lineTo(11, 8.3)
        path.quadTo(11, 11.6, 8, 11.6)
        path.lineTo(5, 11.6)
        path.quadTo(2, 11.6, 2, 8.3)
        path.closeSubpath()
        path.moveTo(11, 5.5)
        path.lineTo(12.2, 5.5)
        path.cubicTo(15.4, 5.5, 15, 9.6, 11, 9.6)
        path.moveTo(1.6, 14)
        path.lineTo(12, 14)
    elif name == "mic":
        path.addRoundedRect(QRectF(6, 1.5, 4, 8), 2, 2)
        path.moveTo(3.7, 7)
        path.cubicTo(3.7, 12.4, 12.3, 12.4, 12.3, 7)
        path.moveTo(8, 11)
        path.lineTo(8, 14)
        path.moveTo(5.7, 14)
        path.lineTo(10.3, 14)
    elif name == "stop":
        path.addRoundedRect(QRectF(4, 4, 8, 8), 1.5, 1.5)
    elif name == "close":
        path.moveTo(4.5, 4.5)
        path.lineTo(11.5, 11.5)
        path.moveTo(11.5, 4.5)
        path.lineTo(4.5, 11.5)
    return path


class DrawerToolButton(QPushButton):
    def __init__(self, icon, label, *, toggle=False, parent=None):
        super().__init__(parent)
        self.set_glyph(icon)
        self.setFixedSize(28, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setToolTip(label)
        self.setAccessibleName(label)
        self.setCheckable(toggle)

    def nextCheckState(self):
        # The checked state reflects the operation's result.
        pass

    def set_glyph(self, icon):
        path = _tool_path(icon)
        center = path.boundingRect().center()
        self._path = path.translated(-center.x(), -center.y())
        self.update()

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        ink = QColor(surface_colors()["text"])
        active = self.isChecked()
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if active or hovered or focused or self.isDown():
            surface = QColor(ink)
            surface.setAlphaF((0.16 if is_light_theme() else 0.19) if active or self.isDown() else 0.09)
            outline = QColor(ink)
            outline.setAlphaF(0.54)
            painter.setPen(QPen(outline, 1) if focused else Qt.PenStyle.NoPen)
            painter.setBrush(surface)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 6, 6)

        if not self.isEnabled():
            ink.setAlphaF(0.40)
        elif not (active or hovered or focused):
            ink.setAlphaF(0.87)
        painter.setPen(QPen(ink, 1.55, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.drawPath(self._path)
