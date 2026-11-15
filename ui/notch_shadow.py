"""A click-through shadow outside the notch window's input region."""

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


class NotchShadow(QWidget):
    MARGIN = 12

    def __init__(self, parent):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput
                         | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._path = QPainterPath()

    def follow(self, bounds, outline, screen_top):
        margin = self.MARGIN
        geometry = QRect(bounds).adjusted(-margin, -margin, margin, margin)
        geometry.setTop(max(geometry.top(), screen_top))
        offset = bounds.topLeft() - geometry.topLeft()
        self._path = outline.translated(offset.x(), offset.y())
        self.setGeometry(geometry)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outside = QPainterPath()
        outside.addRect(self.rect())
        outside.addPath(self._path)
        painter.setClipPath(outside)
        shadow = self._path.translated(0, 3)
        # Overlapping strokes soften the edge without a full-window blur.
        for width, alpha in ((18, 9), (14, 13), (10, 20), (6, 30), (3, 36)):
            painter.setPen(QPen(QColor(0, 0, 0, alpha), width,
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawPath(shadow)
