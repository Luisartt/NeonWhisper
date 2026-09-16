"""Barra flotante que aparece mientras dictas. Nunca roba el foco de la app donde escribes."""
import ctypes
import math
import time
from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from neonwhisper.ui import theme as T
from neonwhisper.ui.widgets import WaveBars, glyph_pixmap

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008


class _PulseDot(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(22, 22)
        self.color = T.CYAN
        self._timer = QTimer(self, interval=40, timeout=self.update)
        self._timer.start()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(11, 11)
        pulse = 0.5 + 0.5 * math.sin(time.monotonic() * 6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(T.qc(self.color, 0.15 + 0.3 * pulse))
        p.drawEllipse(c, 6 + 4 * pulse, 6 + 4 * pulse)
        p.setBrush(QColor(self.color))
        p.drawEllipse(c, 5, 5)


class _CancelButton(QLabel):
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedSize(28, 28)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip("Cancelar (Esc)")
        self._style(False)

    def _style(self, hover: bool):
        self.setPixmap(glyph_pixmap(T.Glyph.CANCEL, T.ICE if hover else T.MUTED, 14))
        self.setStyleSheet(
            f"border-radius: 14px; background: {'rgba(0,229,255,0.14)' if hover else 'transparent'};"
        )

    def enterEvent(self, _):
        self._style(True)

    def leaveEvent(self, _):
        self._style(False)

    def mouseReleaseEvent(self, _):
        self.clicked.emit()


class Overlay(QWidget):
    cancel_requested = Signal()
    MARGIN = 18

    def __init__(self, level_source: Callable[[], float]):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(440, 64 + 2 * self.MARGIN)
        self._accent = T.CYAN
        self._started = 0.0
        self._recording = False

        row = QHBoxLayout(self)
        row.setContentsMargins(self.MARGIN + 18, self.MARGIN, self.MARGIN + 12, self.MARGIN)
        row.setSpacing(12)
        self.dot = _PulseDot()
        self.bars = WaveBars(level_source, height=34)
        self.text = QLabel()
        self.text.setFont(T.display_font(11))
        self.text.setStyleSheet(f"color: {T.ICE};")
        self.text.setMinimumWidth(70)
        self.cancel = _CancelButton()
        self.cancel.clicked.connect(self.cancel_requested)
        row.addWidget(self.dot)
        row.addWidget(self.bars, 1)
        row.addWidget(self.text)
        row.addWidget(self.cancel)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self, duration=180)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self._after_fade)
        self._hide_timer = QTimer(self, singleShot=True, timeout=self.fade_out)
        self._clock = QTimer(self, interval=200, timeout=self._update_clock)

    # --- estados --------------------------------------------------------------
    def show_recording(self) -> None:
        self._recording = True
        self._started = time.monotonic()
        self._set_look(T.CYAN, "recording", "0:00", cancel=True)
        self._clock.start()
        self._appear()

    def show_processing(self, text: str = "Transcribiendo…") -> None:
        self._recording = False
        self._clock.stop()
        self._set_look(T.BLUE, "processing", text, cancel=False)
        self._appear()

    def show_result(self, text: str, error: bool = False, hold_ms: int = 1500) -> None:
        self._recording = False
        self._clock.stop()
        self._set_look(T.DANGER if error else T.OK, "idle", text, cancel=False)
        self._appear()
        self._hide_timer.start(hold_ms)

    def _set_look(self, accent: str, mode: str, text: str, cancel: bool) -> None:
        self._hide_timer.stop()
        self._accent = accent
        self.dot.color = accent
        self.bars.set_mode(mode)
        self.text.setText(text)
        self.text.setStyleSheet(f"color: {T.ICE if accent in (T.CYAN, T.BLUE) else accent};")
        self.cancel.setVisible(cancel)
        self.update()

    def _update_clock(self) -> None:
        secs = int(time.monotonic() - self._started)
        self.text.setText(f"{secs // 60}:{secs % 60:02d}")

    # --- animación y posición ------------------------------------------------
    def _appear(self) -> None:
        if not self.isVisible():
            screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            geo = screen.availableGeometry()
            self.move(geo.center().x() - self.width() // 2, geo.bottom() - self.height() - 28)
            self.setWindowOpacity(0.0)
            self.show()
            self._make_noactivate()
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(1.0)
        self._fade.start()

    def fade_out(self) -> None:
        if not self.isVisible():
            return
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _after_fade(self) -> None:
        if self.windowOpacity() <= 0.01:
            self.hide()

    def _make_noactivate(self) -> None:
        hwnd = int(self.winId())
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongPtrW(ctypes.c_void_p(hwnd), GWL_EXSTYLE)
        user32.SetWindowLongPtrW(
            ctypes.c_void_p(hwnd), GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
        )

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = self.MARGIN
        pill = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)
        radius = pill.height() / 2

        for i in range(m, 0, -2):  # halo neón
            alpha = 0.10 * (1 - i / m) ** 2
            p.setPen(QPen(T.qc(self._accent, alpha), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(pill.adjusted(-i, -i, i, i), radius + i, radius + i)

        path = QPainterPath()
        path.addRoundedRect(pill, radius, radius)
        bg = QLinearGradient(pill.topLeft(), pill.bottomLeft())
        bg.setColorAt(0, QColor(8, 16, 34, 245))
        bg.setColorAt(1, QColor(3, 5, 11, 245))
        p.fillPath(path, bg)
        border = QLinearGradient(pill.topLeft(), pill.topRight())
        border.setColorAt(0, T.qc(T.BLUE, 0.7))
        border.setColorAt(0.5, T.qc(self._accent, 0.95))
        border.setColorAt(1, T.qc(T.BLUE, 0.7))
        p.setPen(QPen(border, 1.4))
        p.drawPath(path)
