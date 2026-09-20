"""Aviso flotante arriba a la izquierda: «parece que entraste a una reunión, ¿la grabo?».

Es pequeño a propósito: el nombre de la reunión, un botón y, mientras graba, el cronómetro y dos
medidores que prueban que sí está entrando el audio. No roba el foco (puedes seguir escribiendo en
Teams o Zoom mientras aparece) y se puede arrastrar a otro lado con el ratón.

Las medidas están fijas y comentadas porque el aviso no tiene margen de error: es una tarjeta de
400 px donde el texto largo tiene que elidirse, nunca salirse.
"""
import ctypes
import math
import time

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from neonwhisper.ui import theme as T
from neonwhisper.ui.widgets import ElidedLabel, glyph_pixmap

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008

MARGIN = 16          # espacio para la sombra alrededor de la tarjeta
CARD_W = 400         # ancho de la tarjeta
CARD_H = 80          # alto con una línea de título y otra de detalle
CARD_H_REC = 112     # alto mientras graba: cabe además la sonda de sonido
RADIUS = T.R_CARD    # el mismo redondeo que las tarjetas de la ventana
PAD_V = 20           # relleno arriba y abajo de la tarjeta
DOT_X = 24           # centro del punto de estado, medido desde el borde de la tarjeta
TEXT_LEFT = 44       # donde empieza el texto: deja libre el halo del punto
SCREEN_GAP = 24      # separación con la esquina de la pantalla
PROMPT_SECONDS = 40  # si no le haces caso, el aviso se va solo
QUIET_SECONDS = 4.0  # sin audio del sistema por más tiempo = aviso de «sin audio de la PC»


class _CloseButton(QLabel):
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedSize(28, 28)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip("Ocultar este aviso")
        self._hover = False
        self.restyle(False)

    def restyle(self, hover: bool, pressed: bool = False) -> None:
        self._hover = hover
        self.setPixmap(glyph_pixmap(T.Glyph.CANCEL, T.ICE if hover or pressed else T.MUTED, 12))
        fill = T.rgba(T.CYAN, 0.26) if pressed else (T.rgba(T.CYAN, 0.14) if hover else "transparent")
        self.setStyleSheet(f"border-radius: 14px; background: {fill};")

    def enterEvent(self, _):
        self.restyle(True)

    def leaveEvent(self, _):
        self.restyle(False)

    def mousePressEvent(self, _):
        self.restyle(True, pressed=True)  # sin esto, el único botón del aviso no acusaba el clic

    def mouseReleaseEvent(self, _):
        self.restyle(self._hover)
        self.clicked.emit()


class _SoundProbe(QWidget):
    """Dos medidores: «Tú» (micrófono) y «Los demás» (lo que suena en la PC).

    Sirve para contestar de un vistazo la pregunta de siempre: ¿de verdad está grabando? Si el
    audio del sistema lleva unos segundos en cero, su barra se pone gris y el aviso lo dice.
    """

    LABEL_W = 64
    BAR_W = 120
    BAR_H = 4
    ROW_H = 12

    def __init__(self, mic_level, system_level):
        super().__init__()
        self.mic_level, self.system_level = mic_level, system_level
        self._mic = 0.0
        self._sys = 0.0
        self._sound_since = 0.0  # última vez que se oyó algo del sistema
        self.setFixedHeight(2 * self.ROW_H + 4)
        self._timer = QTimer(self, interval=50, timeout=self._tick)  # 20 fps

    def start(self) -> None:
        self._mic = self._sys = 0.0
        self._sound_since = time.monotonic()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    @property
    def system_quiet(self) -> bool:
        return time.monotonic() - self._sound_since > QUIET_SECONDS

    def _tick(self) -> None:
        mic, system = float(self.mic_level()), float(self.system_level())
        # Suavizado: los niveles brincan mucho y la barra tiene que leerse, no parpadear.
        self._mic = self._mic * 0.8 + mic * 0.2
        self._sys = self._sys * 0.8 + system * 0.2
        if system > 0.02:
            self._sound_since = time.monotonic()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = T.display_font(7.5)
        p.setFont(font)
        quiet = self.system_quiet
        rows = (("Tú", self._mic, T.CYAN, False), ("Los demás", self._sys, T.BLUE, quiet))
        for i, (name, value, color, off) in enumerate(rows):
            y = i * (self.ROW_H + 4)
            p.setPen(QColor(T.DIM if off else T.MUTED))
            p.drawText(QRectF(0, y, self.LABEL_W - 8, self.ROW_H),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, name)
            track = QRectF(self.LABEL_W, y + (self.ROW_H - self.BAR_H) / 2, self.BAR_W, self.BAR_H)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T.BG3))
            p.drawRoundedRect(track, 2, 2)
            if not off:
                filled = QRectF(track)
                filled.setWidth(max(self.BAR_H, track.width() * min(1.0, value)))
                p.setBrush(QColor(color))
                p.drawRoundedRect(filled, 2, 2)


class MeetingPopup(QWidget):
    """Estados: prompt (pregunta si grabar), recording (cronómetro y «Detener») y saved (aviso breve)."""

    record_requested = Signal()
    stop_requested = Signal()
    open_requested = Signal()
    dismissed = Signal()

    def __init__(self, mic_level=None, system_level=None):
        self.mic_level = mic_level or (lambda: 0.0)
        self.system_level = system_level or (lambda: 0.0)
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(CARD_W + 2 * MARGIN, CARD_H + 2 * MARGIN)
        self.state = "prompt"
        self._started = 0.0
        self._sources = ""
        self._drag: QPoint | None = None
        self._moved = False

        row = QHBoxLayout(self)
        row.setContentsMargins(MARGIN + TEXT_LEFT, MARGIN + PAD_V, MARGIN + 12, MARGIN + PAD_V)
        row.setSpacing(12)
        texts = QVBoxLayout()
        texts.setSpacing(4)
        self.title = ElidedLabel("Reunión detectada")
        self.title.setFixedHeight(18)
        self.detail = ElidedLabel()
        self.detail.setFixedHeight(16)
        self.probe = _SoundProbe(self.mic_level, self.system_level)
        self.probe.hide()
        texts.addWidget(self.title)
        texts.addWidget(self.detail)
        texts.addSpacing(4)
        texts.addWidget(self.probe)
        texts.addStretch(1)
        row.addLayout(texts, 1)
        self.action = QPushButton("Grabar")
        self.action.setProperty("variant", "primary")
        self.action.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.action.setFixedHeight(32)
        self.action.setMinimumWidth(96)
        self.action.clicked.connect(self._on_action)
        row.addWidget(self.action, 0, Qt.AlignmentFlag.AlignVCenter)
        self.close_btn = _CloseButton()
        self.close_btn.clicked.connect(self._on_dismiss)
        row.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self, duration=160)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(lambda: self.hide() if self.windowOpacity() <= 0.01 else None)
        self._auto_hide = QTimer(self, singleShot=True, timeout=self.fade_out)
        self._clock = QTimer(self, interval=500, timeout=self._tick)
        self._pulse = QTimer(self, interval=60, timeout=self.update)  # respiración del punto

    # --- estados --------------------------------------------------------------
    def show_prompt(self, app: str, title: str = "") -> None:
        self.state = "prompt"
        self._clock.stop()
        self._pulse.stop()
        self.probe.stop()
        self.probe.hide()
        self._resize_card()
        self.title.setText(f"Reunión de {app}" if app and app != "Manual" else "Reunión detectada")
        self.detail.setText(title or "¿La grabo y la transcribo?")
        self.action.setText("Grabar")
        self.action.setProperty("variant", "primary")
        self._appear()
        self._auto_hide.start(PROMPT_SECONDS * 1000)

    def show_recording(self, app: str, sources: str = "") -> None:
        """La grabación se queda aquí: cronómetro, sonda de sonido y botón de detener."""
        self.state = "recording"
        self._sources = sources
        self._started = time.monotonic()
        self._auto_hide.stop()
        self.title.setText(f"Grabando {app}" if app and app != "Manual" else "Grabando la reunión")
        self.action.setText("Detener")
        self.action.setProperty("variant", None)
        self.probe.show()
        self.probe.start()
        self._resize_card()
        self._tick()
        self._clock.start()
        self._pulse.start()
        self._appear()

    def show_saved(self, text: str = "Reunión guardada · transcribiendo…") -> None:
        self.state = "saved"
        self._clock.stop()
        self._pulse.stop()
        self.probe.stop()
        self.probe.hide()
        self._resize_card()
        self.title.setText("Listo")
        self.detail.setText(text)
        self.action.setText("Ver")
        self.action.setProperty("variant", None)
        self._appear()
        self._auto_hide.start(4000)

    def set_sources(self, sources: str) -> None:
        """Qué se está grabando ahora («micro + sistema»), por si silencias una fuente."""
        self._sources = sources
        if self.state == "recording":
            self._tick()

    def _resize_card(self) -> None:
        """Mientras graba, la tarjeta crece lo justo para la sonda de sonido."""
        height = CARD_H_REC if self.state == "recording" else CARD_H
        self.setFixedSize(CARD_W + 2 * MARGIN, height + 2 * MARGIN)

    def _tick(self) -> None:
        secs = int(time.monotonic() - self._started)
        clock = f"{secs // 60}:{secs % 60:02d}"
        quiet = self.probe.system_quiet and "sistema" in self._sources
        if quiet:
            self.detail.setText(f"{clock} · sin audio de la PC")
        else:
            self.detail.setText(f"{clock} · {self._sources}" if self._sources else clock)
        self._paint_detail(quiet)

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
        # La hoja de estilos de la app pisa cualquier setFont(): el tamaño va en la del widget.
        self.title.setStyleSheet(
            f"color: {T.TEXT}; font-family: {T.FONT_UI}; font-size: 12pt; font-weight: 600;")
        self._paint_detail(self.state == "recording" and self.probe.system_quiet)
        self.close_btn.restyle(False)
        for w in (self.action,):
            w.style().unpolish(w)
            w.style().polish(w)
        self.update()

    def _paint_detail(self, warn: bool) -> None:
        color = T.REC_INK if warn else T.MUTED
        self.detail.setStyleSheet(
            f"color: {color}; font-family: {T.FONT_UI}; font-size: 9.5pt; font-weight: 400;")

    def _accent(self) -> str:
        return {"recording": T.REC, "saved": T.OK}.get(self.state, T.CYAN)

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
        self.probe.stop()
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

        # Sombra suave y un poco caída, para que la tarjeta se despegue de cualquier escritorio.
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(MARGIN - 4, 0, -1):
            p.setBrush(T.qc("#000000", 0.11 * (1 - i / MARGIN) ** 1.6))
            p.drawRoundedRect(card.adjusted(-i, -i + 4, i, i + 4), RADIUS + i, RADIUS + i)

        path = QPainterPath()
        path.addRoundedRect(card, RADIUS, RADIUS)
        p.fillPath(path, T.qc(T.BG2, 0.97))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(T.qc(accent, 0.55), 2))
        p.drawPath(path)

        # Punto de estado, alineado con el bloque de texto. Respira mientras graba.
        cx = card.left() + DOT_X
        cy = card.top() + PAD_V + 18
        beat = 1.0 if self.state != "recording" else 0.92 + 0.16 * (0.5 + 0.5 * math.sin(time.monotonic() * 6.9))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(T.qc(accent, 0.16))
        p.drawEllipse(QPointF(cx, cy), 11.1 * beat, 11.1 * beat)
        p.setBrush(T.qc(accent, 0.26))
        p.drawEllipse(QPointF(cx, cy), 6.8 * beat, 6.8 * beat)
        p.setBrush(QColor(accent))
        p.drawEllipse(QPointF(cx, cy), 4, 4)
