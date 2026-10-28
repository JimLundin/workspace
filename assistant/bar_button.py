"""One keyboard-accessible capsule button, with ambient facts or a real audio trace."""
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false

import math
from collections import deque

from .ambient import Ambient, Battery, SystemStatus
from .bar_surface import CONTROL_HEIGHT, Pill
from .qt import Qt, QtCore, QtGui, QtWidgets
from .vector_icons import icon


class CapsuleButton(QtWidgets.QToolButton):
    def __init__(self, surface: Pill) -> None:
        super().__init__(surface)
        self.surface = surface
        self.ambient: Ambient | None = None
        self.system = SystemStatus()
        self.listening = False
        self.processing = False
        # Qt owns the current painted angle; timestamps come from the bar's frame loop.
        self.spin_angle: float = 90.0
        self.samples: deque[float] = deque([0.0] * 24, maxlen=24)
        self.meter_available = True
        self.setFixedHeight(CONTROL_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setIconSize(QtCore.QSize(14, 14))
        self.setToolTip("Open Workspace controls · Space: hold to dictate · B: toggle · N: agent")
        self.setAccessibleName("Open Workspace controls")

    def system_changed(self, system: SystemStatus) -> None:
        self.system = system
        self.accessible()
        self.updateGeometry()
        self.update()

    @property
    def plugged_in(self) -> bool:
        return self.ambient is not None and isinstance(self.ambient.power, Battery) and self.ambient.power.powered

    def accessible(self) -> None:
        power = ". Charger connected" if self.plugged_in else ""
        self.setAccessibleName(f"{self.text()}{power}. {self.system.description}. Open Workspace controls")

    def facts(self, ambient: Ambient | None) -> None:
        self.ambient = ambient
        if ambient is not None:
            self.setText(ambient.text)
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
        self.setToolTip("Live microphone signal · release Spacebar to transcribe" if self.meter_available
                        else "Listening · microphone level is unavailable · release Spacebar to transcribe")
        self.update()

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802
        metrics = self.fontMetrics()
        if self.ambient is not None:
            width = metrics.horizontalAdvance(self.ambient.clock) + 14 + metrics.horizontalAdvance(self.ambient.battery_text)
            if self.plugged_in:
                width += 16
            if self.ambient.weather is not None:
                width += 14 + 14 + 5 + metrics.horizontalAdvance(self.ambient.weather.text)
        else:
            width = 14 + 5 + metrics.horizontalAdvance(self.text()) + (81 if self.listening else 0)
        return QtCore.QSize(width + 14 + (len(self.system.alerts) * 19 + 5 if self.system.alerts else 0), CONTROL_HEIGHT)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        option = QtWidgets.QStyleOptionToolButton()
        self.initStyleOption(option)
        option.text, option.icon = "", QtGui.QIcon()
        self.style().drawComplexControl(QtWidgets.QStyle.ComplexControl.CC_ToolButton, option, painter, self)
        painter.setFont(self.font())
        painter.setPen(QtGui.QColor(self.surface.ink.foreground))
        x = 7
        metrics = self.fontMetrics()

        def text(value: str) -> None:
            nonlocal x
            width = metrics.horizontalAdvance(value)
            painter.drawText(QtCore.QRect(x, 0, width, self.height()), Qt.AlignmentFlag.AlignVCenter, value)
            x += width

        def symbol(name: str) -> None:
            nonlocal x
            icon(name, self.surface.ink.foreground).paint(painter, QtCore.QRect(x, 5, 14, 14))
            x += 19

        def divider() -> None:
            nonlocal x
            color = QtGui.QColor(self.surface.ink.foreground)
            color.setAlpha(65)
            painter.setPen(QtGui.QPen(color, 1))
            painter.drawLine(x + 7, 7, x + 7, 17)
            painter.setPen(QtGui.QColor(self.surface.ink.foreground))
            x += 14

        if self.ambient is not None:
            text(self.ambient.clock)
            divider()
            x = self.paint_power(painter, x)
            if self.ambient.weather is not None:
                divider()
                symbol(self.ambient.weather.icon)
                text(self.ambient.weather.text)
        else:
            if self.processing:
                painter.setPen(QtGui.QPen(QtGui.QColor(self.surface.ink.foreground), 1.6,
                                         Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawArc(QtCore.QRectF(x + 1, 6, 12, 12), round(self.spin_angle * 16), 240 * 16)
            else:
                self.icon().paint(painter, QtCore.QRect(x, 5, 14, 14))
            x += 19
            text(self.text())
            if self.listening:
                x += 9
                self.paint_wave(painter, x)
                x += 72
        if self.system.alerts:
            x += 5
            for name in self.system.alerts:
                symbol(name)

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
        if isinstance(self.ambient.power, Battery) and self.ambient.power.percent <= 20 and not self.plugged_in:
            painter.setPen(QtGui.QColor(self.surface.ink.error))
        width = self.fontMetrics().horizontalAdvance(self.ambient.battery_text)
        painter.drawText(QtCore.QRect(x, 0, width, self.height()), Qt.AlignmentFlag.AlignVCenter, self.ambient.battery_text)
        painter.restore()
        return x + width

    def paint_charger(self, painter: QtGui.QPainter, x: int) -> None:
        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor(self.surface.ink.foreground), 1.5,
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPolyline([QtCore.QPoint(x + 10, 5), QtCore.QPoint(x + 4, 12),
                              QtCore.QPoint(x + 9, 12), QtCore.QPoint(x + 4, 19)])
        painter.restore()
