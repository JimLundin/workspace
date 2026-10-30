"""Qt owns connector paths; their factual reasons come from the work catalog."""

from collections.abc import Callable

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.ui_components.text import font
from assistant.work_canvas_connections import CanvasLink, RelationConnection
from assistant.work_canvas_model import CanvasRelation


class ConnectionPath(QtWidgets.QGraphicsPathItem):
    def __init__(self, connection: CanvasLink, menu: Callable[[CanvasRelation], None]) -> None:
        super().__init__()
        self.connection: CanvasLink = connection
        self.menu: Callable[[CanvasRelation], None] = menu
        self.caption: QtWidgets.QGraphicsSimpleTextItem = QtWidgets.QGraphicsSimpleTextItem(self)
        self.caption.setFont(font(8))
        self.caption.setBrush(QtGui.QColor("#b7afc9"))
        self.caption.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setToolTip(connection.reason)
        match connection:
            case RelationConnection():
                self.caption.setText(connection.reason)
                self.setAcceptedMouseButtons(Qt.MouseButton.RightButton)
            case _:
                self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        # Above container surfaces, below their content bubbles. A line behind
        # the parent fill would disappear before reaching its shared source.
        self.setZValue(0)

    def connect(self, start: QtCore.QRectF, end: QtCore.QRectF) -> None:
        left, right = (start, end) if start.center().x() <= end.center().x() else (end, start)
        first = QtCore.QPointF(left.right(), left.center().y())
        last = QtCore.QPointF(right.left(), right.center().y())
        offset = max(48, abs(last.x() - first.x()) / 2)
        path = QtGui.QPainterPath(first)
        path.cubicTo(first + QtCore.QPointF(offset, 0), last - QtCore.QPointF(offset, 0), last)
        self.setPath(path)
        midpoint = path.pointAtPercent(0.5)
        self.caption.setPos(midpoint.x() - self.caption.boundingRect().width() / 2, midpoint.y() - 20)

    def contextMenuEvent(self, event: QtWidgets.QGraphicsSceneContextMenuEvent) -> None:
        match self.connection:
            case RelationConnection(relation=relation):
                self.menu(relation)
                event.accept()
            case _:
                event.ignore()

    def highlight(self, selected: str | None) -> None:
        active = selected in (self.connection.start, self.connection.end)
        pen = QtGui.QPen(QtGui.QColor("#c4a5e8" if active else "#78668e"), 2.4 if active else 1.4)
        pen.setCosmetic(True)
        self.setPen(pen)
