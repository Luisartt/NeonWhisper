"""Aviso flotante arriba a la izquierda: «parece que entraste a una reunión, ¿la grabo?».

Es pequeño a propósito: solo el nombre de la reunión y un botón. No roba el foco (puedes seguir
escribiendo en Teams o Zoom mientras aparece) y se puede arrastrar a otro lado con el ratón.
"""
import ctypes
import math
import time

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from neonwhisper.ui import theme as T
from neonwhisper.ui.widgets import glyph_pixmap

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008

MARGIN = 14          # espacio para la sombra alrededor de la tarjeta
SCREEN_GAP = 24      # separación con la esquina de la pantalla
PROMPT_SECONDS = 40  # si no le haces caso, el aviso se va solo


class _CloseButton(QLabel):
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedSize(22, 22)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip("Ocultar este aviso")
        self.restyle(False)

    def restyle(self, hover: bool) -> None:
        self.setPixmap(glyph_pixmap(T.Glyph.CANCEL, T.ICE if hover else T.DIM, 11))
        self.setStyleSheet(f"border-radius: 11px; background: {T.rgba(T.CYAN, 0.14) if hover else 'transparent'};")

    def enterEvent(self, _):
        self.restyle(True)

    def leaveEvent(self, _):
        self.restyle(False)

    def mouseReleaseEvent(self, _):
        self.clicked.emit()


class MeetingPopup(QWidget):
    """Estados: prompt (pregunta si grabar), recording (cronómetro y «Detener») y saved (aviso breve)."""

    record_requested = Signal()
    stop_requested = Signal()
    open_requested = Signal()
    dismissed = Signal()

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(312 + 2 * MARGIN, 60 + 2 * MARGIN)
        self.state = "prompt"
        self._started = 0.0
        self._sources = ""
        self._drag: QPoint | None = None
        self._moved = False

        row = QHBoxLayout(self)
        row.setContentsMargins(MARGIN + 16, MARGIN, MARGIN + 8, MARGIN)
        row.setSpacing(10)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        self.title = QLabel("Reunión detectada")
        self.title.setFont(T.display_font(10.5))
        self.detail = QLabel()
        self.detail.setFont(T.display_font(8.5, QFont.Weight.Normal))
        texts.addWidget(self.title)
        texts.addWidget(self.detail)
        row.addLayout(texts, 1)
        self.action = QPushButton("Grabar")
        self.action.setProperty("variant", "primary")
        self.action.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.action.setFixedHeight(30)
        self.action.clicked.connect(self._on_action)
        row.addWidget(self.action)
        self.close_btn = _CloseButton()
        self.close_btn.clicked.connect(self._on_dismiss)
        row.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self, duration=160)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(lambda: self.hide() if self.windowOpacity() <= 0.01 else None)
        self._auto_hide = QTimer(self, singleShot=True, timeout=self.fade_out)
        self._clock = QTimer(self, interval=500, timeout=self._tick)
        self._pulse = QTimer(self, interval=60, timeout=self.update)  # latido del punto rojo

    # --- estados --------------------------------------------------------------
    def show_prompt(self, app: str, title: str = "") -> None:
        self.state = "prompt"
        self._clock.stop()
        self._pulse.stop()
        self.title.setText(f"Reunión de {app}" if app and app != "Manual" else "Reunión detectada")
        self.detail.setText((title or "¿La grabo y la transcribo?")[:46])
        self.action.setText("Grabar")
        self.action.setProperty("variant", "primary")
        self._appear()
        self._auto_hide.start(PROMPT_SECONDS * 1000)

    def show_recording(self, app: str, sources: str = "") -> None:
        self.state = "recording"
        self._sources = sources
        self._started = time.monotonic()
        self._auto_hide.stop()
        self.title.setText(f"Grabando {app}" if app and app != "Manual" else "Grabando la reunión")
        self.action.setText("Detener")
        self.action.setProperty("variant", None)
        self._tick()
        self._clock.start()
        self._pulse.start()
        self._appear()

    def show_saved(self, text: str = "Reunión guardada · transcribiendo…") -> None:
        self.state = "saved"
        self._clock.stop()
        self._pulse.stop()
        self.title.setText("Listo")
        self.detail.setText(text[:46])
        self.action.setText("Ver")
        self.action.setProperty("variant", None)
        self._appear()
        self._auto_hide.start(4000)

    def _tick(self) -> None:
        secs = int(time.monotonic() - self._started)
        clock = f"{secs // 60}:{secs % 60:02d}"
        self.detail.setText(f"{clock} · {self._sources}" if self._sources else clock)

    def _on_action(self) -> None:
        if self.state == "recording":
            self.stop_requested.emit()
        elif self.state == "saved":
            self.open_requested.emit()
            self.fade_out()
        else:
            self.record_requested.emit()

    def _on_dismiss(self) -> None:
        self.fade_out()
        self.dismissed.emit()

    # --- apariencia y posición -------------------------------------------------
    def restyle(self) -> None:
        self.title.setStyleSheet(f"color: {T.TEXT};")
        self.detail.setStyleSheet(f"color: {T.MUTED};")
        self.close_btn.restyle(False)
        for w in (self.action,):
            w.style().unpolish(w)
            w.style().polish(w)
        self.update()

    def _accent(self) -> str:
        return {"recording": T.DANGER, "saved": T.OK}.get(self.state, T.CYAN)

    def _appear(self) -> None:
        self.restyle()
        if not self.isVisible():
            if not self._moved:
                screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
                geo = screen.availableGeometry()
                self.move(geo.left() + SCREEN_GAP - MARGIN, geo.top() + SCREEN_GAP - MARGIN)
            self.setWindowOpacity(0.0)
            self.show()
            self._no_activate()
        self.raise_()
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(1.0)
        self._fade.start()

    def fade_out(self) -> None:
        self._auto_hide.stop()
        self._clock.stop()
        self._pulse.stop()
        if not self.isVisible():
            return
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _no_activate(self) -> None:
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongPtrW(ctypes.c_void_p(hwnd), GWL_EXSTYLE)
            user32.SetWindowLongPtrW(
                ctypes.c_void_p(hwnd), GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
            )
        except Exception:  # noqa: BLE001 - fuera de Windows no hace falta
            pass

    # --- arrastrar el aviso ----------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            self.move(event.globalPosition().toPoint() - self._drag)
            self._moved = True

    def mouseReleaseEvent(self, _):
        self._drag = None

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(MARGIN, MARGIN, self.width() - 2 * MARGIN, self.height() - 2 * MARGIN)
        accent = self._accent()

        for i in range(MARGIN, 0, -2):  # sombra suave, para que se vea sobre cualquier fondo
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(T.qc("#000000", 0.05 * (1 - i / MARGIN)))
            p.drawRoundedRect(card.adjusted(-i, -i, i, i), 14 + i, 14 + i)

        path = QPainterPath()
        path.addRoundedRect(card, 14, 14)
        p.fillPath(path, T.qc(T.BG2, 0.97))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(T.qc(accent, 0.55))
        p.drawPath(path)

        # Punto de estado: late mientras graba.
        cx, cy = card.left() + 10, card.center().y()
        pulse = 0.5 + 0.5 * math.sin(time.monotonic() * 5) if self.state == "recording" else 1.0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(T.qc(accent, 0.18 + 0.25 * pulse))
        p.drawEllipse(QPointF(cx, cy), 8, 8)
        p.setBrush(QColor(accent))
        p.drawEllipse(QPointF(cx, cy), 3.6, 3.6)
