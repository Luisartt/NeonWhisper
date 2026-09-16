"""Widgets pintados a mano: logo, orbe del micrófono, barras de voz, switches y teclas."""
import math
import time
from collections import deque
from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import (
    QBrush, QColor, QConicalGradient, QCursor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath,
    QPen, QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QSizePolicy, QWidget,
)

from neonwhisper.hotkeys import pretty_parts
from neonwhisper.ui import theme as T


# --- Íconos -------------------------------------------------------------------
def paint_logo(p: QPainter, rect: QRectF, active: bool = False) -> None:
    s = rect.width()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    inset = s * 0.05
    body = rect.adjusted(inset, inset, -inset, -inset)
    bg = QLinearGradient(body.topLeft(), body.bottomRight())
    bg.setColorAt(0, QColor("#0b1a38" if not active else "#0a2d52"))
    bg.setColorAt(1, QColor("#02040a"))
    p.setPen(QPen(T.qc(T.CYAN, 0.95 if active else 0.6), max(1.0, s * 0.035)))
    p.setBrush(bg)
    p.drawRoundedRect(body, s * 0.24, s * 0.24)

    heights = [0.26, 0.5, 0.7, 0.5, 0.26]
    bw, gap = s * 0.085, s * 0.055
    x0 = rect.center().x() - (len(heights) * bw + (len(heights) - 1) * gap) / 2
    grad = QLinearGradient(0, rect.top() + s * 0.2, 0, rect.bottom() - s * 0.2)
    grad.setColorAt(0, QColor("#ffffff" if active else T.ICE))
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


def make_app_icon(active: bool = False) -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        paint_logo(p, QRectF(0, 0, size, size), active)
        p.end()
        icon.addPixmap(pm)
    return icon


def glyph_pixmap(glyph: str, color: str, px: int = 18) -> QPixmap:
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
    return pm


def glyph_icon(glyph: str, color: str = T.MUTED, hover: str = T.ICE, checked: str = T.ICE, px: int = 18) -> QIcon:
    icon = QIcon()
    icon.addPixmap(glyph_pixmap(glyph, color, px), QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(glyph_pixmap(glyph, hover, px), QIcon.Mode.Active, QIcon.State.Off)
    icon.addPixmap(glyph_pixmap(glyph, checked, px), QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(glyph_pixmap(glyph, checked, px), QIcon.Mode.Active, QIcon.State.On)
    icon.addPixmap(glyph_pixmap(glyph, T.DIM, px), QIcon.Mode.Disabled, QIcon.State.Off)
    return icon


def add_glow(widget: QWidget, color: str = T.CYAN, blur: int = 26, alpha: float = 0.55) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, 0)
    effect.setColor(T.qc(color, alpha))
    widget.setGraphicsEffect(effect)


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    lbl.setWordWrap(wrap)
    return lbl


def card(glow: bool = False) -> QFrame:
    frame = QFrame()
    frame.setObjectName("Card")
    if glow:
        frame.setProperty("glow", "true")
    return frame


class Logo(QWidget):
    def __init__(self, size: int = 36):
        super().__init__()
        self.setFixedSize(size, size)
        self.active = False

    def paintEvent(self, _):
        p = QPainter(self)
        paint_logo(p, QRectF(self.rect()), self.active)


class StatusDot(QWidget):
    COLORS = {"ready": T.OK, "error": T.DANGER, "loading": T.BLUE, "downloading": T.BLUE, "recording": T.CYAN}

    def __init__(self, size: int = 10):
        super().__init__()
        self.setFixedSize(size + 12, size + 12)
        self._size = size
        self.state = "loading"
        self._timer = QTimer(self, interval=50, timeout=self.update)
        self._timer.start()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self.COLORS.get(self.state, T.MUTED)
        c = QPointF(self.width() / 2, self.height() / 2)
        pulse = 0.5 + 0.5 * math.sin(time.monotonic() * (6 if self.state == "recording" else 3))
        if self.state in ("loading", "downloading", "recording"):
            glow_alpha = 0.15 + 0.35 * pulse
        else:
            glow_alpha = 0.3
        g = QRadialGradient(c, self.width() / 2)
        g.setColorAt(0, T.qc(color, glow_alpha))
        g.setColorAt(1, T.qc(color, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, self.width() / 2, self.width() / 2)
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
        self.setMinimumSize(250, 250)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
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
        g = QRadialGradient(c, half)
        g.setColorAt(0.42, T.qc(T.CYAN, min(glow, 0.9)))
        g.setColorAt(0.72, T.qc(T.BLUE, min(glow, 0.9) * 0.3))
        g.setColorAt(1, T.qc(T.BLUE, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, half, half)

        if rec:
            for k in range(3):
                ph = (t * 0.65 + k / 3) % 1.0
                rr = R * (1.12 + ph * 0.7) + lvl * R * 0.12
                p.setPen(QPen(T.qc(T.CYAN, (1 - ph) * 0.5), 1.6))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, rr, rr)
            ticks = 90
            for i in range(ticks):
                ang = i / ticks * math.tau
                noise = 0.55 + 0.45 * math.sin(i * 1.9 + t * 11) * math.sin(i * 0.7 - t * 4)
                length = R * 0.04 + R * 0.34 * lvl * max(0.15, noise)
                inner = R * 1.1
                col = T.qc(T.ICE if i % 2 else T.CYAN, 0.35 + 0.6 * lvl)
                p.setPen(QPen(col, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(
                    QPointF(c.x() + math.cos(ang) * inner, c.y() + math.sin(ang) * inner),
                    QPointF(c.x() + math.cos(ang) * (inner + length), c.y() + math.sin(ang) * (inner + length)),
                )

        core = QRadialGradient(c - QPointF(R * 0.3, R * 0.4), R * 1.5)
        if rec:
            core.setColorAt(0, QColor("#0d5d8f"))
            core.setColorAt(0.55, QColor("#07284d"))
        else:
            core.setColorAt(0, QColor("#132f5a" if not disabled else "#0c1426"))
            core.setColorAt(0.55, QColor("#081327"))
        core.setColorAt(1, QColor("#02050c"))
        ring = QConicalGradient(c, -t * 70)
        ring.setColorAt(0.0, QColor(T.CYAN))
        ring.setColorAt(0.33, QColor(T.BLUE))
        ring.setColorAt(0.66, QColor(T.INDIGO))
        ring.setColorAt(1.0, QColor(T.CYAN))
        p.setBrush(core)
        p.setPen(QPen(QBrush(ring), 2.6) if not disabled else QPen(QColor(T.LINE_HI), 2))
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
            p.setBrush(QColor("#ffffff"))
            p.drawRoundedRect(QRectF(c.x() - side / 2, c.y() - side / 2, side, side), side * 0.22, side * 0.22)
        else:
            f = QFont(T.icon_family())
            f.setPixelSize(int(R * 0.72))
            p.setFont(f)
            p.setPen(QColor(T.DIM if disabled else (T.ICE if not self._hover else "#ffffff")))
            p.drawText(QRectF(c.x() - R, c.y() - R, 2 * R, 2 * R), Qt.AlignmentFlag.AlignCenter, T.Glyph.MIC)


# --- Barras de voz ------------------------------------------------------------
class WaveBars(QWidget):
    BAR_W, GAP = 4.0, 3.0

    def __init__(self, level_source: Callable[[], float], height: int = 56):
        super().__init__()
        self.level_source = level_source
        self.mode = "idle"  # idle | recording | processing
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._history: deque[float] = deque([0.0] * 160, maxlen=160)
        self._t0 = time.monotonic()
        self._timer = QTimer(self, interval=33, timeout=self._tick)
        self._timer.start()

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
        n = max(1, int((w + self.GAP) // (self.BAR_W + self.GAP)))
        x0 = (w - (n * self.BAR_W + (n - 1) * self.GAP)) / 2
        t = time.monotonic() - self._t0
        values = list(self._history)[-n:]
        values = [0.0] * (n - len(values)) + values

        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0, QColor(T.BLUE))
        grad.setColorAt(0.6, QColor(T.CYAN))
        grad.setColorAt(1, QColor(T.ICE))
        p.setPen(Qt.PenStyle.NoPen)
        mid = h / 2
        for i in range(n):
            if self.mode == "recording":
                v = values[i]
                alpha = 0.3 + 0.7 * (i / max(1, n - 1))
            elif self.mode == "processing":
                v = 0.18 + 0.22 * (0.5 + 0.5 * math.sin(t * 7 - i * 0.28))
                alpha = 0.35 + 0.5 * (0.5 + 0.5 * math.sin(t * 7 - i * 0.28))
            else:
                v = 0.03 + 0.03 * (0.5 + 0.5 * math.sin(t * 1.5 + i * 0.25))
                alpha = 0.35
            bh = max(self.BAR_W, v * (h - 4))
            x = x0 + i * (self.BAR_W + self.GAP)
            p.setOpacity(alpha)
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(QRectF(x, mid - bh / 2, self.BAR_W, bh), self.BAR_W / 2, self.BAR_W / 2)
        p.setOpacity(1.0)


# --- Controles ----------------------------------------------------------------
class ToggleSwitch(QAbstractButton):
    def __init__(self, checked: bool = False):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._pos = 1.0 if checked else 0.0
        self._anim = QVariantAnimation(self, duration=160, easingCurve=QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._set_pos)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        return QSize(46, 26)

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
        off = QColor(T.BG3)
        grad = QLinearGradient(r.topLeft(), r.topRight())
        grad.setColorAt(0, QColor(T.BLUE))
        grad.setColorAt(1, QColor(T.CYAN))
        p.setPen(QPen(QColor(T.LINE_HI), 1))
        p.setBrush(off)
        p.drawPath(track)
        if self._pos > 0:
            p.setOpacity(self._pos)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(grad))
            p.drawPath(track)
            p.setOpacity(1)
        d = r.height() - 6
        x = r.left() + 3 + self._pos * (r.width() - d - 6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff") if self.isChecked() else QColor(T.MUTED))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))


class KeyCaps(QWidget):
    CAP_STYLE = (
        f"background: #0a1428; color: {T.ICE}; border: 1px solid rgba(0,229,255,0.45);"
        "border-bottom: 3px solid #0b6f8c; border-radius: 8px; padding: 3px 11px;"
        "font-family: Bahnschrift; font-size: 11pt; font-weight: 600;"
    )

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
                plus.setStyleSheet(f"color: {T.DIM}; font-size: 11pt;")
                self._layout.addWidget(plus)
            cap = QLabel(part)
            cap.setStyleSheet(self.CAP_STYLE)
            cap.ensurePolished()
            cap.setMinimumSize(cap.sizeHint())
            cap.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._layout.addWidget(cap)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


class GlyphLabel(QLabel):
    """Ícono de la fuente de símbolos de Windows (como pixmap, para que la hoja de estilos no lo pise)."""

    def __init__(self, glyph: str, color: str = T.CYAN, px: int = 18):
        super().__init__()
        self.setPixmap(glyph_pixmap(glyph, color, px))
        self.setFixedSize(px + 4, px + 4)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_color(self, glyph: str, color: str, px: int = 18) -> None:
        self.setPixmap(glyph_pixmap(glyph, color, px))
