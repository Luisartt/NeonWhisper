"""Widgets pintados a mano: logo, orbe del micrófono, barras de voz, switches, teclas y tarjetas de tema."""
import html
import math
import time
from collections import deque
from collections.abc import Callable

from PySide6.QtCore import (
    QEasingCurve, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QConicalGradient, QCursor, QFont, QFontMetrics, QIcon, QLinearGradient, QPainter, QPainterPath,
    QPen, QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLayout, QSizePolicy, QWidget,
)

from neonwhisper.hotkeys import pretty_parts
from neonwhisper.ui import theme as T
from neonwhisper.ui.overlay_styles import STYLES, paint_pill


# --- Re-estilizado al cambiar de tema -----------------------------------------
def on_restyle(widget: QWidget, fn: Callable[[], None]) -> None:
    """Registra algo que hay que volver a calcular al cambiar de tema (íconos, brillos, HTML) y lo aplica ya."""
    widget._restyle_fns = [*getattr(widget, "_restyle_fns", []), fn]
    fn()


def repolish(widget: QWidget) -> None:
    """Vuelve a aplicar la hoja de estilos después de cambiar una propiedad (role, tone, variant)."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def set_tone(widget: QWidget, tone: str | None) -> None:
    widget.setProperty("tone", tone)
    repolish(widget)


def restyle(root: QWidget) -> None:
    """Vuelve a calcular lo que la hoja de estilos no sabe hacer sola: íconos, brillos y HTML.

    Se llama justo después de `theme.apply_stylesheet()`, que ya volvió a «polish» cada widget de
    la app; repetirlo aquí widget por widget costaba otros ~75 ms y no cambiaba ni un píxel.

    Cada callback va protegido a propósito. Si uno solo se cae —porque apunta a un objeto de C++
    que Qt ya borró: una fila que se acaba de rehacer, un efecto reemplazado— antes se llevaba por
    delante el resto del cambio de tema y la ventana se quedaba a medio vestir, con unos colores
    nuevos y otros viejos. Ahora ese callback se descarta y los demás siguen.
    """
    for w in (root, *root.findChildren(QWidget)):
        try:
            fns = getattr(w, "_restyle_fns", None)
        except RuntimeError:
            continue  # el widget desapareció mientras recorríamos la lista
        if not fns:
            continue
        vivos = []
        for fn in fns:
            try:
                fn()
            except RuntimeError:
                continue  # el widget o el efecto del callback ya no existen: se olvida
            vivos.append(fn)
        if len(vivos) != len(fns):
            try:
                w._restyle_fns = vivos
            except RuntimeError:
                pass


# --- Íconos -------------------------------------------------------------------
def paint_logo(p: QPainter, rect: QRectF, active: bool = False) -> None:
    s = rect.width()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    inset = s * 0.05
    body = rect.adjusted(inset, inset, -inset, -inset)
    bg = QLinearGradient(body.topLeft(), body.bottomRight())
    bg.setColorAt(0, QColor(T.LOGO_ACTIVE if active else T.LOGO_IDLE))
    bg.setColorAt(1, QColor(T.ORB_DEEP))
    p.setPen(QPen(T.qc(T.CYAN, 0.95 if active else 0.6), max(1.0, s * 0.035)))
    p.setBrush(bg)
    p.drawRoundedRect(body, s * 0.24, s * 0.24)

    heights = [0.26, 0.5, 0.7, 0.5, 0.26]
    bw, gap = s * 0.085, s * 0.055
    x0 = rect.center().x() - (len(heights) * bw + (len(heights) - 1) * gap) / 2
    grad = QLinearGradient(0, rect.top() + s * 0.2, 0, rect.bottom() - s * 0.2)
    grad.setColorAt(0, QColor(T.HI if active else T.ICE))
    grad.setColorAt(0.5, QColor(T.CYAN))
    grad.setColorAt(1, QColor(T.BLUE))
    p.setPen(Qt.PenStyle.NoPen)
    for pass_, (widen, alpha) in enumerate(((s * 0.05, 0.18), (0.0, 1.0))):
        for i, h in enumerate(heights):
            bh = s * h * 0.78 + widen
            x = x0 + i * (bw + gap) - widen / 2
            y = rect.center().y() - bh / 2
            if pass_ == 0:
                p.setBrush(T.qc(T.CYAN, alpha))
            else:
                p.setBrush(QBrush(grad))
            w = bw + widen
            p.drawRoundedRect(QRectF(x, y, w, bh), w / 2, w / 2)


# Los íconos solo dependen del tema, así que se pintan una vez por tema y se reparten después.
# La clave lleva el tema porque los colores vienen de él; al cambiarlo se usa (o se llena) su hueco.
_iconos_app: dict[tuple[str, bool], QIcon] = {}
_pixmaps: dict[tuple[str, str, int], QPixmap] = {}
_iconos_glifo: dict[tuple[str, str, str, str, str, int], QIcon] = {}


def clear_icon_cache() -> None:
    """Olvida los íconos guardados. Solo hace falta si se cambian los colores de un tema en marcha."""
    _iconos_app.clear()
    _pixmaps.clear()
    _iconos_glifo.clear()


def make_app_icon(active: bool = False) -> QIcon:
    clave = (T.THEME.key, active)
    icono = _iconos_app.get(clave)
    if icono is not None:
        return icono
    icono = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        paint_logo(p, QRectF(0, 0, size, size), active)
        p.end()
        icono.addPixmap(pm)
    _iconos_app[clave] = icono
    return icono


def glyph_pixmap(glyph: str, color: str, px: int = 18) -> QPixmap:
    # El color ya viene resuelto a hex, así que sirve de clave por sí solo: no hace falta el tema.
    clave = (glyph, color, px)
    pm = _pixmaps.get(clave)
    if pm is not None:
        return pm
    dpr = 2.0
    pm = QPixmap(int(px * dpr), int(px * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    f = QFont(T.icon_family())
    f.setPixelSize(int(px * 0.85))
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(QRectF(0, 0, px, px), Qt.AlignmentFlag.AlignCenter, glyph)
    p.end()
    _pixmaps[clave] = pm
    return pm


def glyph_icon(glyph: str, color: str | None = None, hover: str | None = None, checked: str | None = None,
               px: int = 18) -> QIcon:
    color, hover = color or T.MUTED, hover or T.ICE
    checked = checked or T.ICE
    # T.DIM entra en la clave porque es el color del estado apagado, y cambia con el tema.
    clave = (glyph, color, hover, checked, T.DIM, px)
    icono = _iconos_glifo.get(clave)
    if icono is not None:
        return icono
    icono = QIcon()
    icono.addPixmap(glyph_pixmap(glyph, color, px), QIcon.Mode.Normal, QIcon.State.Off)
    icono.addPixmap(glyph_pixmap(glyph, hover, px), QIcon.Mode.Active, QIcon.State.Off)
    icono.addPixmap(glyph_pixmap(glyph, checked, px), QIcon.Mode.Normal, QIcon.State.On)
    icono.addPixmap(glyph_pixmap(glyph, checked, px), QIcon.Mode.Active, QIcon.State.On)
    icono.addPixmap(glyph_pixmap(glyph, T.DIM, px), QIcon.Mode.Disabled, QIcon.State.Off)
    _iconos_glifo[clave] = icono
    return icono


def add_glow(widget: QWidget, color: str | None = None, blur: int = 26, alpha: float = 0.55) -> None:
    """Halo de color detrás de un texto. En los temas claros no se usa: ensucia en vez de lucir."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, 0)
    widget.setGraphicsEffect(effect)

    def pintar() -> None:
        # Se pregunta por el efecto de ahora en vez de recordar el de antes: si alguien le pone
        # otro al mismo widget, Qt borra el viejo y quedarse con él reventaba el cambio de tema.
        actual = widget.graphicsEffect()
        if actual is None:
            return
        actual.setBlurRadius(round(blur * max(0.5, T.GLOW)))
        actual.setColor(T.qc(color or T.CYAN, alpha * T.GLOW if T.THEME.dark else 0.0))

    on_restyle(widget, pintar)


def set_glyph_icon(button: QAbstractButton, factory: Callable[[], QIcon]) -> None:
    """Ícono que se vuelve a dibujar con los colores del tema activo."""
    on_restyle(button, lambda: button.setIcon(factory()))


class WrapLabel(QLabel):
    """Párrafo de varias líneas con interlineado holgado.

    Qt no entiende `line-height` en la hoja de estilos, pero sí en texto enriquecido: por eso el
    texto se envuelve en un div (y se escapa, porque aquí caen transcripciones del usuario).
    """

    def __init__(self, text: str = ""):
        super().__init__()
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setText(text)

    def setText(self, text: str) -> None:
        self._plain = text
        super().setText(f"<div style='line-height:140%'>{html.escape(text)}</div>")
        self._fit()

    def text(self) -> str:
        return self._plain

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        """Reserva el alto que el texto necesita al ancho que le tocó.

        Con texto enriquecido, `sizeHint` se calcula al ancho «ideal» del documento (una línea
        larga), y ese alto no es el que hace falta cuando el párrafo se reparte en varias líneas.
        Un área de scroll reparte alturas a partir de ese sizeHint, así que el último renglón se
        quedaba cortado por la mitad. Fijando el mínimo a lo que de verdad ocupa, el reparto no
        puede dejarlo corto.
        """
        width = self.width()
        if width <= 0:
            return
        needed = self.heightForWidth(width)
        # Solo si cambia: asignarlo en cada `resizeEvent` dispararía otro reparto, y otro.
        if needed > 0 and needed != self.minimumHeight():
            self.setMinimumHeight(needed)


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    lbl = WrapLabel(text) if wrap else QLabel(text)
    if role:
        lbl.setProperty("role", role)
    if wrap:
        # Qt no sabe por su cuenta que el alto de un párrafo depende del ancho que le toque: sin
        # esto el reparto le da el alto de menos renglones de los que necesita y el último sale
        # cortado por la mitad. Se nota al estrechar los párrafos, porque pasan a ocupar más
        # renglones, y con el interlineado al 140 % de `WrapLabel`, que pide todavía más alto.
        policy = lbl.sizePolicy()
        policy.setHeightForWidth(True)
        lbl.setSizePolicy(policy)
    return lbl


class CardFlow(QLayout):
    """Tarjetas del mismo ancho que bajan a la siguiente fila cuando ya no caben.

    Existe porque en la ventana angosta (960 px) una fila de cuatro tarjetas se aplastaba y el
    contenido se salía; así se reacomodan solas en dos filas y crecen al ensanchar la ventana.
    """

    def __init__(self, min_width: int = 180, spacing: int = 12, parent: QWidget | None = None):
        super().__init__(parent)
        self._items: list = []
        self._min_w = min_width
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    # --- lo que QLayout necesita ---------------------------------------------
    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), place=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, place=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        m = self.contentsMargins()
        height = max((i.sizeHint().height() for i in self._items), default=0)
        return QSize(self._min_w + m.left() + m.right(), height + m.top() + m.bottom())

    # --- acomodo --------------------------------------------------------------
    def _arrange(self, rect: QRect, place: bool) -> int:
        if not self._items:
            return 0
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        gap = self.spacing()
        cols = max(1, min(len(self._items), (area.width() + gap) // (self._min_w + gap)))
        item_w = (area.width() - (cols - 1) * gap) / cols
        row_h = max(i.sizeHint().height() for i in self._items)
        rows = -(-len(self._items) // cols)
        if place:
            for index, item in enumerate(self._items):
                x = area.x() + (index % cols) * (item_w + gap)
                y = area.y() + (index // cols) * (row_h + gap)
                item.setGeometry(QRect(QPoint(round(x), round(y)), QSize(round(item_w), row_h)))
        return rows * row_h + (rows - 1) * gap + m.top() + m.bottom()


def add_shadow(widget: QWidget, blur: int = 18, dy: int = 4, alpha: float = 0.05,
               accent: bool = False) -> QGraphicsDropShadowEffect:
    """Sombra suave debajo de una tarjeta o un botón, para despegarla del fondo sin verse dura."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    widget.setGraphicsEffect(effect)

    def pintar() -> None:
        # Igual que en add_glow: el efecto se pregunta al widget, no se recuerda.
        actual = widget.graphicsEffect()
        if actual is not None:
            # Misma geometría en todos los temas; sobre fondo oscuro hay que cargar más la tinta.
            actual.setColor(T.qc(T.CYAN if accent else "#000000",
                                 alpha * (1.6 if T.THEME.dark else 1.0)))

    on_restyle(widget, pintar)
    return effect


def lift_on_hover(widget: QWidget, effect: QGraphicsDropShadowEffect) -> None:
    """Al pasar el ratón, la tarjeta solo levanta la sombra: nada de saltos ni cambios de color."""
    def shadow(hover: bool) -> None:
        effect.setBlurRadius(24 if hover else 18)
        effect.setOffset(0, 6 if hover else 4)
        effect.setColor(T.qc("#000000", (0.08 if hover else 0.05) * (1.6 if T.THEME.dark else 1.0)))

    widget.enterEvent = lambda _e: shadow(True)
    widget.leaveEvent = lambda _e: shadow(False)


def card(glow: bool = False, shadow: bool = True) -> QFrame:
    frame = QFrame()
    frame.setObjectName("Card")
    if glow:
        frame.setProperty("glow", "true")
    if shadow:
        add_shadow(frame)
    return frame


class ElidedLabel(QLabel):
    """Etiqueta que corta el texto con «…» cuando no cabe, en vez de desbordarse de su tarjeta."""

    def __init__(self, text: str = "", role: str | None = None):
        super().__init__(text)
        self._full = text
        if role:
            self.setProperty("role", role)

    def minimumSizeHint(self) -> QSize:
        # Puede encogerse hasta casi nada: así una fila larga no obliga a la tarjeta a crecer
        # (y el texto se corta con «…» en vez de salirse), pero sigue pidiendo su ancho natural.
        return QSize(24, super().minimumSizeHint().height())

    def setText(self, text: str) -> None:
        self._full = text
        super().setText(text)
        self.setToolTip(text)

    def text(self) -> str:
        return self._full

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setPen(self.palette().color(self.foregroundRole()))
        fm = QFontMetrics(self.font())
        shown = fm.elidedText(self._full, Qt.TextElideMode.ElideRight, self.width())
        p.drawText(self.rect(), int(self.alignment()) | int(Qt.TextFlag.TextSingleLine), shown)


class ClickCard(QFrame):
    """Tarjeta que responde al clic completo (el panel de inicio lleva a su pestaña)."""

    clicked = Signal()

    def __init__(self, name: str = "Tile"):
        super().__init__()
        self.setObjectName(name)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        lift_on_hover(self, add_shadow(self))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()


class Logo(QWidget):
    def __init__(self, size: int = 36):
        super().__init__()
        self.setFixedSize(size, size)
        self.active = False

    def paintEvent(self, _):
        p = QPainter(self)
        paint_logo(p, QRectF(self.rect()), self.active)


class StatusDot(QWidget):
    """Núcleo, anillo y halo planos. Respira solo cuando algo está pasando."""

    def __init__(self, size: int = 8):
        super().__init__()
        self.setFixedSize(26, 26)
        self._size = size
        self.state = "loading"
        self._timer = QTimer(self, interval=50, timeout=self._tick)
        self._timer.start()

    def _color(self) -> str:
        return {"ready": T.OK, "error": T.DANGER, "loading": T.BLUE,
                "downloading": T.BLUE, "recording": T.REC}.get(self.state, T.MUTED)

    def _alive(self) -> bool:
        return self.state in ("loading", "downloading", "recording")

    def _tick(self) -> None:
        if self._alive():  # en reposo no hay nada que animar
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self._color()
        c = QPointF(self.width() / 2, self.height() / 2)
        phase = 0.5 + 0.5 * math.sin(time.monotonic() * 2 * math.pi * 1.1) if self._alive() else 0.5
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(T.qc(color, 0.14 + 0.14 * phase))
        halo = 9.6 + 1.5 * phase
        p.drawEllipse(c, halo, halo)
        p.setBrush(T.qc(color, 0.26))
        p.drawEllipse(c, 6.8, 6.8)
        p.setBrush(QColor(color))
        p.drawEllipse(c, self._size / 2, self._size / 2)


# --- Orbe del micrófono -------------------------------------------------------
class MicOrb(QWidget):
    clicked = Signal()

    def __init__(self, level_source: Callable[[], float]):
        super().__init__()
        self.level_source = level_source
        self.state = "disabled"  # disabled | idle | recording | processing
        self._level = 0.0
        self._hover = False
        self._t0 = time.monotonic()
        self.setMinimumSize(160, 160)  # con 250 fijos la ventana no bajaba del mínimo
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._timer = QTimer(self, interval=16, timeout=self._tick)
        self._timer.start()

    def set_state(self, state: str) -> None:
        self.state = state
        self.update()

    def _tick(self):
        target = self.level_source() if self.state == "recording" else 0.0
        self._level = target if target > self._level else self._level * 0.86 + target * 0.14
        self.update()

    def enterEvent(self, _):
        self._hover = True

    def leaveEvent(self, _):
        self._hover = False

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = time.monotonic() - self._t0
        c = QPointF(self.width() / 2, self.height() / 2)
        half = min(self.width(), self.height()) / 2
        R = half * 0.46
        lvl = self._level
        rec, proc, disabled = self.state == "recording", self.state == "processing", self.state == "disabled"

        glow = {
            "idle": 0.16 + 0.05 * math.sin(t * 1.8),
            "recording": 0.32 + 0.55 * lvl,
            "processing": 0.26 + 0.06 * math.sin(t * 5),
            "disabled": 0.05,
        }[self.state] + (0.06 if self._hover and not disabled else 0)
        glow *= T.GLOW  # en los temas claros el aura tiene que ser un susurro
        g = QRadialGradient(c, half)
        g.setColorAt(0.42, T.qc(T.CYAN, min(glow, 0.9)))
        g.setColorAt(0.72, T.qc(T.BLUE, min(glow, 0.9) * 0.3))
        g.setColorAt(1, T.qc(T.BLUE, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, half, half)

        if rec:
            for k, ring_alpha in enumerate((0.30, 0.16)):  # dos anillos que respiran, no tres
                ph = (t * 0.65 + k / 2) % 1.0
                rr = R * (1.12 + ph * 0.7) + lvl * R * 0.12
                p.setPen(QPen(T.qc(T.CYAN, (1 - ph) * ring_alpha * 2), 1.8))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, rr, rr)
            ticks = 64
            for i in range(ticks):
                ang = i / ticks * math.tau
                noise = 0.55 + 0.45 * math.sin(i * 1.9 + t * 11) * math.sin(i * 0.7 - t * 4)
                length = R * 0.04 + R * 0.34 * lvl * max(0.15, noise)
                inner = R * 1.1
                col = T.qc(T.ICE if i % 2 else T.CYAN, 0.35 + 0.6 * lvl)
                p.setPen(QPen(col, 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(
                    QPointF(c.x() + math.cos(ang) * inner, c.y() + math.sin(ang) * inner),
                    QPointF(c.x() + math.cos(ang) * (inner + length), c.y() + math.sin(ang) * (inner + length)),
                )

        core = QRadialGradient(c - QPointF(R * 0.3, R * 0.4), R * 1.5)
        if rec:
            core.setColorAt(0, QColor(T.ORB_HI))
            core.setColorAt(0.55, QColor(T.ORB_HI2))
        else:
            core.setColorAt(0, QColor(T.ORB_OFF if disabled else T.ORB_IDLE))
            core.setColorAt(0.55, QColor(T.ORB_MID))
        core.setColorAt(1, QColor(T.ORB_DEEP))
        ring = QConicalGradient(c, -t * 70)
        ring.setColorAt(0.0, QColor(T.CYAN))
        ring.setColorAt(0.33, QColor(T.BLUE))
        ring.setColorAt(0.66, QColor(T.INDIGO))
        ring.setColorAt(1.0, QColor(T.CYAN))
        p.setBrush(core)
        p.setPen(QPen(QBrush(ring), 3.0) if not disabled else QPen(QColor(T.LINE_HI), 2))
        p.drawEllipse(c, R, R)

        if proc:
            arc = QRectF(c.x() - R * 1.2, c.y() - R * 1.2, R * 2.4, R * 2.4)
            spin = QConicalGradient(c, -t * 300)
            spin.setColorAt(0.0, QColor(T.ICE))
            spin.setColorAt(0.25, T.qc(T.CYAN, 0.0))
            spin.setColorAt(1.0, T.qc(T.CYAN, 0.0))
            p.setPen(QPen(QBrush(spin), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(arc)

        if rec:
            side = R * 0.52
            p.setPen(Qt.PenStyle.NoPen)
            # En pastel el núcleo es durazno claro: el cuadro de detener va en tinta, no en blanco.
            p.setBrush(QColor(T.HI if T.THEME.dark else T.REC_INK))
            p.drawRoundedRect(QRectF(c.x() - side / 2, c.y() - side / 2, side, side), side * 0.22, side * 0.22)
        else:
            f = QFont(T.icon_family())
            f.setPixelSize(int(R * 0.72))
            p.setFont(f)
            p.setPen(QColor(T.DIM if disabled else (T.ICE if not self._hover else T.HI)))
            p.drawText(QRectF(c.x() - R, c.y() - R, 2 * R, 2 * R), Qt.AlignmentFlag.AlignCenter, T.Glyph.MIC)


# --- Barras de voz ------------------------------------------------------------
class WaveBars(QWidget):
    def __init__(self, level_source: Callable[[], float], height: int = 56):
        super().__init__()
        self.level_source = level_source
        self.mode = "idle"  # idle | recording | processing
        self.stops: tuple[tuple[float, str], ...] | None = None  # None = color plano del tema
        self.bar_w, self.gap = 5.0, 4.0
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._history: deque[float] = deque([0.0] * 160, maxlen=160)
        self._t0 = time.monotonic()
        self._timer = QTimer(self, interval=33, timeout=self._tick)
        self._timer.start()

    def set_style(self, stops: tuple[tuple[float, str], ...], bar_w: float, gap: float) -> None:
        self.stops, self.bar_w, self.gap = stops, max(1.5, bar_w), max(1.5, gap)
        self.update()

    def set_mode(self, mode: str) -> None:
        if mode == "recording" and self.mode != "recording":
            self._history.extend([0.0] * self._history.maxlen)
        self.mode = mode

    def _tick(self):
        if self.mode == "recording":
            self._history.append(self.level_source())
        if self.isVisible():
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        bw, gap = self.bar_w, self.gap
        n = max(1, int((w + gap) // (bw + gap)))
        x0 = (w - (n * bw + (n - 1) * gap)) / 2
        t = time.monotonic() - self._t0
        values = list(self._history)[-n:]
        values = [0.0] * (n - len(values)) + values

        # Con `stops` (la barra flotante) manda la paleta del diseño; si no, color plano del tema
        # y lo único que cambia es la transparencia: se lee mejor y no ensucia en los temas claros.
        if self.stops:
            grad = QLinearGradient(0, 0, w, 0)
            for pos, color in self.stops:
                grad.setColorAt(pos, QColor(color))
            brush = QBrush(grad)
        else:
            brush = QBrush(QColor(T.CYAN))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(brush)
        mid = h / 2
        top = (h - 4) * 0.78  # altura máxima de una barra
        for i in range(n):
            if self.mode == "recording":
                v = values[i]
                alpha = 0.55 + 0.45 * (i / max(1, n - 1))
            elif self.mode == "processing":
                wave = 0.5 + 0.5 * math.sin(t * 7 - i * 0.28)
                v = 0.18 + 0.22 * wave
                alpha = 0.40 + 0.45 * wave
            else:
                v = 0.0
                alpha = 0.22
            bh = max(bw, v * top)  # en reposo quedan puntitos: es parte de la gracia
            x = x0 + i * (bw + gap)
            p.setOpacity(alpha)
            p.drawRoundedRect(QRectF(x, mid - bh / 2, bw, bh), bw / 2, bw / 2)
        p.setOpacity(1.0)


# --- Barra de progreso ----------------------------------------------------------
class NeonProgress(QWidget):
    """Barra de progreso neón. Modos: active (con brillo animado), paused, indeterminate, error."""

    def __init__(self, height: int = 8):
        super().__init__()
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.value = 0.0
        self.mode = "active"
        self._t0 = time.monotonic()
        self._timer = QTimer(self, interval=33, timeout=self.update)

    def set_progress(self, value: float, mode: str = "active") -> None:
        self.value = max(0.0, min(1.0, value))
        self.mode = mode
        if mode in ("active", "indeterminate"):
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        if self.mode in ("active", "indeterminate"):
            self._timer.start()
        super().showEvent(event)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        track = QPainterPath()
        track.addRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        p.fillPath(track, QColor(T.BG3))
        p.setClipPath(track)
        t = time.monotonic() - self._t0

        if self.mode == "indeterminate":
            seg = w * 0.28
            x = ((t * 0.7) % 1.35 - 0.35) * w
            grad = QLinearGradient(x, 0, x + seg, 0)
            grad.setColorAt(0, T.qc(T.CYAN, 0))
            grad.setColorAt(0.5, QColor(T.CYAN))
            grad.setColorAt(1, T.qc(T.CYAN, 0))
            p.fillRect(QRectF(x, 0, seg, h), QBrush(grad))
        elif self.value > 0:
            fw = max(h, w * self.value)
            grad = QLinearGradient(0, 0, fw, 0)
            if self.mode == "active":
                grad.setColorAt(0, QColor(T.BLUE))
                grad.setColorAt(0.75, QColor(T.CYAN))
                grad.setColorAt(1, QColor(T.ICE))
            elif self.mode == "error":
                grad.setColorAt(0, T.qc(T.DANGER, 0.5))
                grad.setColorAt(1, QColor(T.DANGER))
            else:  # paused
                grad.setColorAt(0, QColor(T.LINE))
                grad.setColorAt(1, QColor(T.LINE_HI))
            fill = QPainterPath()
            fill.addRoundedRect(QRectF(0, 0, fw, h), h / 2, h / 2)
            p.fillPath(fill, QBrush(grad))
            if self.mode == "active":
                band = 70.0
                x = (t * 0.55 % 1.0) * (fw + band) - band
                shine = QLinearGradient(x, 0, x + band, 0)
                shine.setColorAt(0, QColor(255, 255, 255, 0))
                shine.setColorAt(0.5, QColor(255, 255, 255, 110))
                shine.setColorAt(1, QColor(255, 255, 255, 0))
                p.setClipPath(fill)
                p.fillRect(QRectF(x, 0, band, h), QBrush(shine))
        p.setClipping(False)
        p.setPen(QPen(QColor(T.LINE_HI), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), h / 2, h / 2)


# --- Controles ----------------------------------------------------------------
class ToggleSwitch(QAbstractButton):
    def __init__(self, checked: bool = False):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)  # sin esto no llega el aviso de hover
        self._pos = 1.0 if checked else 0.0
        self._anim = QVariantAnimation(self, duration=160, easingCurve=QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._set_pos)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        return QSize(46, 26)  # con el botoncito de 18 px que pide el informe

    def _set_pos(self, v):
        self._pos = float(v)
        self.update()

    def _animate(self, checked: bool):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        track = QPainterPath()
        track.addRoundedRect(r, r.height() / 2, r.height() / 2)
        # Al pasar el raton, el borde se enciende: es el unico aviso de que se puede pulsar.
        hover = self.underMouse()
        off = QColor(T.THEME.hover_bg if hover else T.BG3)
        grad = QLinearGradient(r.topLeft(), r.topRight())
        grad.setColorAt(0, QColor(T.BLUE))
        grad.setColorAt(1, QColor(T.CYAN))
        p.setPen(QPen(QColor(T.CYAN if hover else T.LINE_HI), 1))
        p.setBrush(off)
        p.drawPath(track)
        if self._pos > 0:
            p.setOpacity(self._pos)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(grad))
            p.drawPath(track)
            p.setOpacity(1)
        d = 18.0
        x = r.left() + 3 + self._pos * (r.width() - d - 6)
        p.setPen(Qt.PenStyle.NoPen)
        # El botoncito va sobre el relleno de color: en los temas claros el que resalta es el blanco.
        knob = (T.ICE if T.THEME.dark else T.ON_ACCENT) if self.isChecked() else T.MUTED
        p.setBrush(QColor(knob))
        p.drawEllipse(QRectF(x, r.center().y() - d / 2, d, d))


class KeyCaps(QWidget):
    def __init__(self, hotkey: str = ""):
        super().__init__()
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self.set_hotkey(hotkey)

    def set_hotkey(self, hotkey: str) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, part in enumerate(pretty_parts(hotkey)):
            if i:
                plus = QLabel("+")
                plus.setObjectName("KeyPlus")
                self._layout.addWidget(plus)
            cap = QLabel(part)
            cap.setObjectName("KeyCap")
            cap.ensurePolished()
            cap.setMinimumSize(cap.sizeHint())
            cap.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._layout.addWidget(cap)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


class GlyphLabel(QLabel):
    """Ícono de la fuente de símbolos de Windows (como pixmap, para que la hoja de estilos no lo pise)."""

    def __init__(self, glyph: str, color: str = "CYAN", px: int = 18):
        """`color` es el nombre de un color del tema (CYAN, MUTED…) o un hex fijo."""
        super().__init__()
        self.setFixedSize(px + 4, px + 4)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_glyph(glyph, color, px)

    def set_glyph(self, glyph: str, color: str = "CYAN", px: int = 18) -> None:
        self._restyle_fns = []
        on_restyle(self, lambda: self.setPixmap(glyph_pixmap(glyph, getattr(T, color, color), px)))


# --- Selector de diseño de la barra flotante --------------------------------------
class OverlayStyleCard(QAbstractButton):
    """Tarjeta con una miniatura del diseño sobre un fondo mixto, para que se note la transparencia."""

    def __init__(self, key: str, settings):
        super().__init__()
        self.look = STYLES[key]
        self.settings = settings
        self.setCheckable(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFixedHeight(164)
        self.setMinimumWidth(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip(f"{self.look.name} · {self.look.description}")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        look, s = self.look, self.settings
        checked, hover = self.isChecked(), self.underMouse()
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(T.CYAN if checked else T.LINE_HI if hover else T.LINE), 2 if checked else 1))
        p.setBrush(QColor(T.BG3 if checked or hover else T.BG0))
        p.drawRoundedRect(r, 12, 12)

        # Escena: un documento claro sobre un escritorio oscuro.
        scene = r.adjusted(10, 10, -10, -52)
        clip = QPainterPath()
        clip.addRoundedRect(scene, 8, 8)
        p.save()
        p.setClipPath(clip)
        desk = QLinearGradient(scene.topLeft(), scene.bottomRight())
        desk.setColorAt(0, QColor("#1d3158"))
        desk.setColorAt(1, QColor("#0a1122"))
        p.fillRect(scene, desk)
        doc = QRectF(scene.left() + scene.width() * 0.08, scene.top() + 10, scene.width() * 0.52, scene.height())
        p.fillRect(doc, QColor("#e8edf5"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#b4bfd1"))
        for i in range(7):
            width = doc.width() - 20 if i % 3 != 2 else (doc.width() - 20) * 0.55
            p.drawRoundedRect(QRectF(doc.left() + 10, doc.top() + 10 + i * 11, width, 4), 2, 2)
        p.restore()

        # Miniatura de la barra, a la misma escala en los tres diseños.
        k = scene.width() * 0.86 / 440
        pw, ph = look.width * k, look.height * k
        pill = QRectF(scene.center().x() - pw / 2, scene.bottom() - ph - 12, pw, ph)
        p.setOpacity(s.overlay_opacity)
        paint_pill(p, pill, look, "recording", s.overlay_bg_opacity, 6)
        accent, cy = look.accents["recording"], pill.center().y()
        dot_x = pill.left() + ph * 0.45
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(T.qc(accent, 0.3))
        p.drawEllipse(QPointF(dot_x, cy), ph * 0.14, ph * 0.14)
        p.setBrush(QColor(accent))
        p.drawEllipse(QPointF(dot_x, cy), ph * 0.08, ph * 0.08)
        font = T.display_font(8, look.font_weight)
        font.setPixelSize(max(7, round(ph * 0.3)))
        text_rect = QRectF(pill.right() - ph * 0.4 - ph, pill.top(), ph, ph)
        p.setFont(font)
        p.setPen(QColor(look.text["recording"]))
        p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, "0:04")
        left, right = dot_x + ph * 0.35, text_rect.right() - ph * 0.85
        bw, gap = max(1.5, look.bar_width * k * 1.2), max(1.4, look.bar_gap * k * 1.2)
        n = max(1, int((right - left + gap) // (bw + gap)))
        grad = QLinearGradient(left, 0, right, 0)
        for pos, color in look.bars:
            grad.setColorAt(pos, QColor(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        for i in range(n):
            v = 0.15 + 0.8 * abs(math.sin(i * 0.9) * math.sin(i * 0.31 + 1.2))
            bh = max(bw, v * ph * 0.52)
            p.setOpacity(s.overlay_opacity * (0.3 + 0.7 * i / max(1, n - 1)))
            p.drawRoundedRect(QRectF(left + i * (bw + gap), cy - bh / 2, bw, bh), bw / 2, bw / 2)
        p.setOpacity(1.0)

        # Nombre y descripción.
        p.setFont(T.display_font(10.5))
        p.setPen(QColor(T.ICE if checked else T.TEXT))
        p.drawText(QRectF(r.left() + 14, scene.bottom() + 9, r.width() - 50, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, look.name)
        small = QFont("Segoe UI")
        small.setPointSizeF(8.5)
        p.setFont(small)
        p.setPen(QColor(T.MUTED if checked else T.DIM))
        desc = QFontMetrics(small).elidedText(look.description, Qt.TextElideMode.ElideRight, int(r.width() - 28))
        p.drawText(QRectF(r.left() + 14, scene.bottom() + 28, r.width() - 28, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, desc)
        if checked:
            p.drawPixmap(QPointF(r.right() - 30, scene.bottom() + 11), glyph_pixmap(T.Glyph.CHECK, T.CYAN, 16))


# --- Selector de tema de la interfaz ------------------------------------------
class ThemeCard(QAbstractButton):
    """Tarjeta con una maqueta en miniatura de la app pintada con la paleta del tema."""

    def __init__(self, key: str):
        super().__init__()
        self.theme = T.THEMES[key]
        self.setCheckable(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFixedHeight(164)
        self.setMinimumWidth(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip(f"{self.theme.name} · {self.theme.description}")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        u, checked, hover = self.theme, self.isChecked(), self.underMouse()
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(T.CYAN if checked else T.LINE_HI if hover else T.LINE), 2 if checked else 1))
        p.setBrush(QColor(T.BG3 if checked or hover else T.BG0))
        p.drawRoundedRect(r, 12, 12)

        # Maqueta de la ventana con los colores del tema.
        scene = r.adjusted(10, 10, -10, -52)
        clip = QPainterPath()
        clip.addRoundedRect(scene, 8, 8)
        p.save()
        p.setClipPath(clip)
        p.fillRect(scene, QColor(u.bg0))
        side = QRectF(scene.left(), scene.top(), scene.width() * 0.3, scene.height())
        p.fillRect(side, QColor(u.bg1))
        p.setPen(QPen(QColor(u.line), 1))
        p.drawLine(side.topRight(), side.bottomRight())

        # Píldoras de navegación: la primera, activa.
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(3):
            pill = QRectF(side.left() + 7, side.top() + 10 + i * 14, side.width() - 14, 9)
            if i == 0:
                p.setBrush(T.qc(u.accent, 0.20))
                p.drawRoundedRect(pill, 4, 4)
                p.setBrush(QColor(u.ice))
            else:
                p.setBrush(QColor(u.dim))
            p.drawRoundedRect(QRectF(pill.left() + 4, pill.center().y() - 1.5, pill.width() * 0.62, 3), 1.5, 1.5)

        # Tarjeta con título, ondas y botón primario.
        body = QRectF(side.right() + 9, scene.top() + 10, scene.right() - side.right() - 18, scene.height() - 20)
        p.setBrush(QColor(u.bg2))
        p.setPen(QPen(QColor(u.line), 1))
        p.drawRoundedRect(body, 6, 6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(u.accent))
        p.drawRoundedRect(QRectF(body.left() + 8, body.top() + 8, body.width() * 0.34, 3), 1.5, 1.5)
        p.setBrush(QColor(u.muted))
        p.drawRoundedRect(QRectF(body.left() + 8, body.top() + 15, body.width() * 0.62, 3), 1.5, 1.5)

        waves = QRectF(body.left() + 8, body.top() + 24, body.width() - 16, body.height() * 0.38)
        grad = QLinearGradient(waves.left(), 0, waves.right(), 0)
        grad.setColorAt(0, QColor(u.blue))
        grad.setColorAt(0.6, QColor(u.accent))
        grad.setColorAt(1, QColor(u.ice))
        p.setBrush(QBrush(grad))
        bw, gap = 3.0, 2.5
        n = max(1, int((waves.width() + gap) // (bw + gap)))
        for i in range(n):
            v = 0.18 + 0.82 * abs(math.sin(i * 0.8) * math.sin(i * 0.27 + 0.9))
            bh = max(bw, v * waves.height())
            p.setOpacity(0.35 + 0.65 * i / max(1, n - 1))
            p.drawRoundedRect(QRectF(waves.left() + i * (bw + gap), waves.center().y() - bh / 2, bw, bh), 1.5, 1.5)
        p.setOpacity(1.0)

        btn = QRectF(body.left() + 8, body.bottom() - 16, body.width() * 0.4, 10)
        fill = QLinearGradient(btn.topLeft(), btn.bottomRight())
        fill.setColorAt(0, QColor(u.primary_from))
        fill.setColorAt(1, QColor(u.primary_to))
        p.setBrush(QBrush(fill))
        p.drawRoundedRect(btn, 5, 5)
        p.setBrush(QColor(u.bg3))
        p.setPen(QPen(QColor(u.line_hi), 1))
        p.drawRoundedRect(QRectF(btn.right() + 6, btn.top(), btn.width() * 0.62, 10), 5, 5)
        p.restore()

        # Nombre y descripción.
        p.setFont(T.display_font(10.5))
        p.setPen(QColor(T.ICE if checked else T.TEXT))
        p.drawText(QRectF(r.left() + 14, scene.bottom() + 9, r.width() - 50, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, u.name)
        small = QFont("Segoe UI")
        small.setPointSizeF(8.5)
        p.setFont(small)
        p.setPen(QColor(T.MUTED if checked else T.DIM))
        desc = QFontMetrics(small).elidedText(u.description, Qt.TextElideMode.ElideRight, int(r.width() - 28))
        p.drawText(QRectF(r.left() + 14, scene.bottom() + 28, r.width() - 28, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, desc)
        if checked:
            p.drawPixmap(QPointF(r.right() - 30, scene.bottom() + 11), glyph_pixmap(T.Glyph.CHECK, T.CYAN, 16))
