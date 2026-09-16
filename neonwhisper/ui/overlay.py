"""Barra flotante que aparece mientras dictas. Nunca roba el foco de la app donde escribes."""
import ctypes
import math
import random
import time
from collections.abc import Callable

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from neonwhisper.ui import theme as T
from neonwhisper.ui.overlay_styles import OverlayStyle, get_style, paint_pill
from neonwhisper.ui.widgets import WaveBars, glyph_pixmap

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008


def demo_level(t: float) -> float:
    """Nivel de voz simulado para la vista previa: sílabas dentro de frases."""
    syllables = max(0.0, math.sin(t * 9.0)) ** 0.6
    phrase = 0.5 + 0.5 * math.sin(t * 1.3)
    return max(0.0, min(1.0, 0.1 + 0.75 * syllables * (0.35 + 0.65 * phrase) + random.uniform(-0.05, 0.05)))


class _PulseDot(QWidget):
    BASE = 22

    def __init__(self):
        super().__init__()
        self.setFixedSize(self.BASE, self.BASE)
        self.color = T.CYAN
        self._timer = QTimer(self, interval=40, timeout=self.update)
        self._timer.start()

    def set_scale(self, scale: float) -> None:
        self.setFixedSize(round(self.BASE * scale), round(self.BASE * scale))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(self.width() / self.BASE, self.height() / self.BASE)
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
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip("Cancelar (Esc)")
        self.look = get_style("")
        self.scale = 1.0
        self.set_look(self.look, 1.0)

    def set_look(self, look: OverlayStyle, scale: float) -> None:
        self.look, self.scale = look, scale
        self.setFixedSize(round(28 * scale), round(28 * scale))
        self._style(self.underMouse())

    def _style(self, hover: bool):
        self.setPixmap(glyph_pixmap(T.Glyph.CANCEL, self.look.icon_hover if hover else self.look.icon,
                                    max(9, round(14 * self.scale))))
        self.setStyleSheet(
            f"border-radius: {self.width() // 2}px; background: {self.look.hover_bg if hover else 'transparent'};"
        )

    def enterEvent(self, _):
        self._style(True)

    def leaveEvent(self, _):
        self._style(False)

    def mouseReleaseEvent(self, _):
        self.clicked.emit()


class Overlay(QWidget):
    cancel_requested = Signal()
    BOTTOM_GAP = 28

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
        self._level_source = level_source
        self._state = "recording"
        self._cancel_shown = True
        self._started = 0.0
        self._demo = False

        self.row = QHBoxLayout(self)
        self.dot = _PulseDot()
        self.bars = WaveBars(self._level, height=34)
        self.text = QLabel()
        self.cancel = _CancelButton()
        self.cancel.clicked.connect(self.cancel_requested)
        self.row.addWidget(self.dot)
        self.row.addWidget(self.bars, 1)
        self.row.addWidget(self.text)
        self.row.addWidget(self.cancel)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self, duration=180)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self._after_fade)
        self._hide_timer = QTimer(self, singleShot=True, timeout=self.fade_out)
        self._preview_timer = QTimer(self, singleShot=True, timeout=self._end_preview)
        self._clock = QTimer(self, interval=200, timeout=self._update_clock)
        self.apply_appearance("neon", 1.0, 0.96, 1.0)

    # --- apariencia -----------------------------------------------------------
    def apply_appearance(self, style: str, scale: float, bg_opacity: float, opacity: float) -> None:
        """Diseño, tamaño (1.0 = 100 %), opacidad del fondo y opacidad de toda la barra."""
        self.look = look = get_style(style)
        self.scale = s = max(0.5, min(2.0, scale))
        self.bg_opacity = max(0.0, min(1.0, bg_opacity))
        self.opacity = max(0.2, min(1.0, opacity))
        self.margin = m = max(8, round(18 * s))
        pill_h = round(look.height * s)
        self.setFixedSize(round(look.width * s) + 2 * m, pill_h + 2 * m)
        self.row.setContentsMargins(m + round(pill_h * 0.28), m, m + round(pill_h * 0.19), m)
        self.row.setSpacing(round(12 * s))
        self.dot.set_scale(s * look.height / 64)
        self.bars.setFixedHeight(round(pill_h * 0.53))
        self.bars.set_style(look.bars, look.bar_width * s, look.bar_gap * s)
        self.text.setFont(T.display_font(look.font_size * s, look.font_weight))
        self.text.setMinimumWidth(round(70 * s))
        self.cancel.set_look(look, s * look.height / 64)
        self._set_state(self._state, self.text.text(), self._cancel_shown)
        if self.isVisible():
            self._place(self.screen())
            fading_out = self._fade.state() == QAbstractAnimation.State.Running and self._fade.endValue() == 0.0
            if not fading_out:
                self._fade.stop()
                self.setWindowOpacity(self.opacity)

    # --- estados --------------------------------------------------------------
    def show_recording(self) -> None:
        self._stop_preview()
        self._started = time.monotonic()
        self._set_state("recording", "0:00", cancel=True)
        self._clock.start()
        self._appear()

    def show_processing(self, text: str = "Transcribiendo…") -> None:
        self._stop_preview()
        self._clock.stop()
        self._set_state("processing", text, cancel=False)
        self._appear()

    def show_result(self, text: str, error: bool = False, hold_ms: int = 1500) -> None:
        self._stop_preview()
        self._clock.stop()
        self._set_state("error" if error else "ok", text, cancel=False)
        self._appear()
        self._hide_timer.start(hold_ms)

    def show_preview(self, ms: int = 3000) -> None:
        """Muestra la barra con voz simulada para ver cómo se ve el diseño elegido."""
        if not self._demo:
            self._demo = True
            self._started = time.monotonic()
            self._set_state("recording", "0:00", cancel=True)
            self._clock.start()
            self._appear()
        self._preview_timer.start(ms)

    def _end_preview(self) -> None:
        if self._demo:
            self._demo = False
            self._clock.stop()
            self.fade_out()

    def _stop_preview(self) -> None:
        self._demo = False
        self._preview_timer.stop()

    def _level(self) -> float:
        return demo_level(time.monotonic()) if self._demo else self._level_source()

    def _set_state(self, state: str, text: str, cancel: bool) -> None:
        self._hide_timer.stop()
        self._state = state
        self._cancel_shown = cancel
        self.dot.color = self.look.accents[state]
        self.bars.set_mode({"recording": "recording", "processing": "processing"}.get(state, "idle"))
        self.text.setText(text)
        self.text.setStyleSheet(f"color: {self.look.text[state]};")
        self.cancel.setVisible(cancel)
        self.update()

    def _update_clock(self) -> None:
        secs = int(time.monotonic() - self._started)
        self.text.setText(f"{secs // 60}:{secs % 60:02d}")

    # --- animación y posición ------------------------------------------------
    def _place(self, screen) -> None:
        geo = (screen or QGuiApplication.primaryScreen()).availableGeometry()
        self.move(geo.center().x() - self.width() // 2, geo.bottom() - self.height() - self.BOTTOM_GAP)

    def _appear(self) -> None:
        if not self.isVisible():
            self._place(QGuiApplication.screenAt(QCursor.pos()))
            self.setWindowOpacity(0.0)
            self.show()
            self._make_noactivate()
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(self.opacity)
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
        m = self.margin
        pill = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)
        paint_pill(p, pill, self.look, self._state, self.bg_opacity, m)
