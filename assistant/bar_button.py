"""Read-only toolbar status and separators between independent functions."""

import math
from collections import deque

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.ambient import Ambient, Battery, SystemStatus
from assistant.bar_surface import CONTROL_HEIGHT, Pill
from assistant.qt_runtime import prepare
from assistant.vector_icons import icon

prepare()


class StatusView(QtWidgets.QLabel):
    def __init__(self, surface: Pill) -> None:
        super().__init__(surface)
        self.surface = surface
        self.symbol: str = "clock"
        self.ambient: Ambient | None = None
        self.system = SystemStatus()
        self.description: str = "Ready"
        self.listening = False
        self.processing = False
        # Qt owns the current painted angle; timestamps come from the bar's frame loop.
        self.spin_angle: float = 90.0
        self.samples: deque[float] = deque([0.0] * 24, maxlen=24)
        self.meter_available = True
        self.setFixedHeight(CONTROL_HEIGHT)
        # The painted icons need the full measured width; QLabel's native
        # minimum hint only measures its text and would clip these observations.
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setStyleSheet("background: transparent; border: none; padding: 0; font: 500 12px 'Segoe UI';")
        self.setToolTip("Clock, battery and local weather")

    def system_changed(self, system: SystemStatus) -> None:
        self.system = system
        self.accessible()
        self.updateGeometry()
        self.update()

    @property
    def plugged_in(self) -> bool:
        match self.ambient:
            case Ambient(power=Battery(powered=True)):
                return True
            case _:
                return False

    def accessible(self) -> None:
        facts = (
            self.ambient.text if self.ambient is not None else self.description,
            "Charger connected" if self.plugged_in else "",
            self.system.description,
        )
        description = ". ".join(value for value in facts if value)
        self.setAccessibleName(description)
        self.setToolTip(description)

    def describe(self, description: str) -> None:
        self.description = description
        self.accessible()

    def facts(self, ambient: Ambient | None) -> None:
        self.ambient = ambient
        self.setText("  ·  ".join(value for value in (ambient.clock, ambient.battery_text) if value) if ambient is not None else "")
        self.accessible()
        self.updateGeometry()
        self.update()

    def capture(self, *, listening: bool, processing: bool) -> None:
        if listening and not self.listening:
            self.samples = deque([0.0] * 24, maxlen=24)
            self.meter_available = True
        self.processing = processing
        self.listening = listening
        self.updateGeometry()
        self.update()

    def pulse(self, now: float, *, animate: bool) -> bool:
        if not self.processing:
            return False
        self.spin_angle = (90 - now * 300) % 360 if animate else 90.0
        self.update()
        return animate

    def observe(self, level: float | None) -> None:
        self.meter_available = level is not None
        self.samples.append(min(1.0, math.log10(1 + max(0.0, level or 0.0) * 90) / math.log10(91)))
        self.describe(
            "Listening · live microphone signal · use Stop to finish"
            if self.meter_available
            else "Listening · microphone level is unavailable · use Stop to finish"
        )
        self.update()

    def sizeHint(self) -> QtCore.QSize:
        if self.ambient is not None:
            metrics = self.fontMetrics()
            width = metrics.horizontalAdvance(self.ambient.clock) + 14 + metrics.horizontalAdvance(self.ambient.battery_text)
            if self.plugged_in:
                width += 16
            if self.ambient.weather is not None:
                width += 19
        else:
            width = 14 + (81 if self.listening else 0)
        return QtCore.QSize(width + 10 + len(self.system.alerts) * 19, CONTROL_HEIGHT)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setFont(self.font())
        painter.setPen(QtGui.QColor(self.surface.ink.foreground))
        x = 5

        def symbol(name: str) -> None:
            nonlocal x
            icon(name, self.surface.ink.foreground).paint(painter, QtCore.QRect(x, 5, 14, 14))
            x += 14

        # System observations precede activity so its spinner/microphone stays
        # next to Stop, including when speakers are audible.
        for name in self.system.alerts:
            symbol(name)
            x += 5
        if self.ambient is not None:
            width = self.fontMetrics().horizontalAdvance(self.ambient.clock)
            painter.drawText(QtCore.QRect(x, 0, width, self.height()), Qt.AlignmentFlag.AlignVCenter, self.ambient.clock)
            x += width + 14
            x = self.paint_power(painter, x)
            if self.ambient.weather is not None:
                x += 5
                symbol(self.ambient.weather.icon)
        else:
            if self.processing:
                painter.setPen(QtGui.QPen(QtGui.QColor(self.surface.ink.foreground), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawArc(QtCore.QRectF(x + 1, 6, 12, 12), round(self.spin_angle * 16), 240 * 16)
            else:
                icon(self.symbol, self.surface.ink.foreground).paint(painter, QtCore.QRect(x, 5, 14, 14))
            x += 14
            if self.listening:
                x += 9
                self.paint_wave(painter, x)
                x += 72

    def paint_wave(self, painter: QtGui.QPainter, x: int) -> None:
        color = QtGui.QColor(self.surface.ink.foreground)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        for index, sample in enumerate(self.samples):
            height = 2 + sample * 14
            painter.drawRoundedRect(QtCore.QRectF(x + index * 3, 12 - height / 2, 2, height), 1, 1)

    def paint_power(self, painter: QtGui.QPainter, x: int) -> int:
        if self.ambient is None:
            return x
        if self.plugged_in:
            self.paint_charger(painter, x)
            x += 16
        painter.save()
        match self.ambient.power:
            case Battery(percent=percent, powered=False) if percent <= 20:
                painter.setPen(QtGui.QColor(self.surface.ink.error))
            case _:
                pass
        width = self.fontMetrics().horizontalAdvance(self.ambient.battery_text)
        painter.drawText(QtCore.QRect(x, 0, width, self.height()), Qt.AlignmentFlag.AlignVCenter, self.ambient.battery_text)
        painter.restore()
        return x + width

    def paint_charger(self, painter: QtGui.QPainter, x: int) -> None:
        painter.save()
        painter.setPen(
            QtGui.QPen(QtGui.QColor(self.surface.ink.foreground), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        )
        painter.drawPolyline([QtCore.QPoint(x + 10, 5), QtCore.QPoint(x + 4, 12), QtCore.QPoint(x + 9, 12), QtCore.QPoint(x + 4, 19)])
        painter.restore()


class Divider(QtWidgets.QWidget):
    """One visual boundary between functions, never inside a status/control group."""

    def __init__(self, surface: Pill) -> None:
        super().__init__(surface)
        self.surface = surface
        self.setFixedSize(9, 16)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        color = QtGui.QColor(self.surface.ink.foreground)
        color.setAlpha(65)
        painter.setPen(QtGui.QPen(color, 1))
        painter.drawLine(4, 3, 4, 13)
