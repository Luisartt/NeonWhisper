"""Ventana principal: Inicio, Historial y Ajustes."""
import html
import os
import webbrowser
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QShowEvent
from PySide6.QtWidgets import (
    QBoxLayout, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QGraphicsOpacityEffect, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
    QSlider, QStackedWidget, QVBoxLayout, QWidget,
)

from neonwhisper import __version__
from neonwhisper.audio import device_name, list_input_devices, resolve_input_device
from neonwhisper.config import LANGUAGES, MODEL_SIZES, MODELS, SUMMARY_MODELS
from neonwhisper.fmt import fmt_bytes, fmt_eta, fmt_speed
from neonwhisper.history import Entry
from neonwhisper.mictest import MeetingAudioTester, MicTester
from neonwhisper.paths import DATA_DIR, MODELS_DIR
from neonwhisper.summarizer import TEMPLATES
from neonwhisper.ui import theme as T
from neonwhisper.updater import RELEASES_URL, Updater, can_update
from neonwhisper.ui.widgets import (
    CardFlow, ClickCard, ElidedLabel, GlyphLabel, KeyCaps, Logo, MicOrb, NeonProgress, OverlayStyleCard,
    StatusDot, readable_hint,
    ThemeCard, ToggleSwitch, WaveBars, add_glow, add_shadow, card, glyph_icon, label, make_app_icon, on_restyle,
    repolish, restyle, set_glyph_icon, set_tone,
)
from neonwhisper.ui.overlay_styles import STYLES

if TYPE_CHECKING:
    from neonwhisper.app import Controller

MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
COMPACT_WIDTH = 820  # por debajo de esto, Reuniones se apila y esconde los iconos en un menú

# --- Escala de espaciado ------------------------------------------------------
# Todo el aire de la ventana sale de aquí, en múltiplos de 4. Las medidas de página
# (T.PAGE_MARGIN, T.SECTION_GAP) y de tarjeta (T.CARD_PAD, T.CARD_GAP) viven en el tema;
# estos son los tramos de dentro, para no volver a escribir números sueltos.
GAP_XS = 4    # una línea y su apoyo: título → datos, rótulo → campo
GAP_S = 8     # hermanos apretados dentro de un mismo bloque
GAP_M = 12    # controles de una misma fila, y sangría de las filas del panel
GAP_L = 16    # bloques distintos dentro de una tarjeta
GAP_XL = 24   # el rótulo de una fila de ajustes y su control
SHADOW_ROOM = GAP_S      # hueco al final de una lista para que no se corte la sombra
SCROLL_GUTTER = GAP_S    # lo que se le resta al margen derecho por la barra de desplazamiento
ACTION_EDGE = GAP_L      # margen derecho cuando la fila termina en botones de icono
CONTROL_H = 36           # alto de un botón secundario (y lado de uno que solo lleva icono)
WAVE_H = 36              # alto de los medidores de voz
SLIDER_W = 200           # ancho de los deslizadores de Ajustes
TEXT_MAX = 520           # ancho máximo de un párrafo de apoyo (~80 caracteres por renglón)

# Color del estado de una reunión (en el panel de inicio y en la lista de Reuniones).
STATE_TONES = {"grabando": "rec", "transcribiendo": "accent", "resumiendo": "accent", "lista": "ok",
               "error": "danger"}
# «Lista» y «Error» llevan además un glifo: con daltonismo rojo-verde el verde y el rojo de las dos
# píldoras se ven del mismo gris, y se perdía la alarma de un vistazo. El color deja de ser el único
# que lo cuenta.
STATE_GLYPHS = {"lista": T.Glyph.CHECK, "error": T.Glyph.CANCEL}


class NoWheelComboBox(QComboBox):
    """La rueda del mouse desplaza la página en vez de cambiar la opción por accidente."""

    def __init__(self):
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event) -> None:
        event.ignore()


class NoWheelSlider(QSlider):
    def __init__(self, orientation):
        super().__init__(orientation)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event) -> None:
        event.ignore()


def human_date(stamp: str) -> str:
    dt = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
    if dt.date() == date.today():
        day = "Hoy"
    elif dt.date() == date.today() - timedelta(days=1):
        day = "Ayer"
    else:
        day = f"{dt.day} {MONTHS[dt.month - 1]} {dt.year}"
    return f"{day} · {dt:%H:%M}"


def mode_hint(mode: str) -> str:
    return "Presiona para empezar · otra vez para pegar" if mode == "toggle" else "Mantén presionado mientras hablas · suelta para pegar"


def scrollable(inner: QWidget, limit: bool = True) -> QScrollArea:
    """Área con scroll vertical. En pantallas grandes el contenido no se estira: se centra."""
    if limit:
        inner.setMaximumWidth(T.CONTENT_MAX)
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
    area.setWidget(inner)
    return area


def page_body(page: QWidget) -> QVBoxLayout:
    """Contenido de una página: crece con la ventana pero nunca pasa de CONTENT_MAX."""
    outer = QHBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    body = QWidget()
    body.setMaximumWidth(T.CONTENT_MAX)
    # Los dos espaciadores solo se reparten lo que sobra cuando el cuerpo ya llegó a su tope:
    # con una alineación en su lugar, el cuerpo se quedaría en su ancho natural y sería un hilo.
    outer.addStretch(1)
    outer.addWidget(body, 1000)
    outer.addStretch(1)
    return QVBoxLayout(body)


def empty_state(glyph: str, text: str, compact: bool = False) -> QWidget:
    """Hueco amable: un ícono, aire y una frase. La misma pieza en las cuatro páginas.

    En versión `compact` cabe dentro de una tarjeta del panel de inicio, con el mismo tono.
    """
    host = QWidget()
    v = QVBoxLayout(host)
    pad = GAP_M if compact else GAP_XL
    v.setContentsMargins(0, pad, 0, pad)
    v.setSpacing(GAP_M)
    v.addStretch(1)
    v.addWidget(GlyphLabel(glyph, "LINE_HI", 28 if compact else 40), 0, Qt.AlignmentFlag.AlignHCenter)
    message = label(text, "muted", wrap=True)
    message.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    if compact:
        v.addWidget(message)  # en una tarjeta angosta ocupa el ancho entero y el texto va centrado
    else:
        # Con una alineación, Qt le daba su ancho «natural» y la frase se cortaba a media palabra.
        # Los dos espaciadores le dan un ancho de verdad y el tope la deja en una columna legible.
        message.setMaximumWidth(420)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(message, 4)
        row.addStretch(1)
        v.addLayout(row)
    v.addStretch(1)
    host.setMinimumHeight(112 if compact else 220)
    return host


def paragraph(text: str = "", role: str = "muted") -> QLabel:
    """Párrafo de apoyo, cortado en TEXT_MAX.

    A lo ancho de la ventana un renglón llegaba a 128 caracteres: a partir de ~80 el ojo pierde
    el salto de línea y el párrafo se escanea en vez de leerse.
    """
    lbl = label(text, role, wrap=True)
    lbl.setMaximumWidth(TEXT_MAX)
    return lbl


def page_header(eyebrow: str, title: str, subtitle: str = "") -> QVBoxLayout:
    box = QVBoxLayout()
    box.setSpacing(GAP_XS)
    box.addWidget(label(eyebrow, "eyebrow"))
    h1 = label(title, "h1")
    box.addWidget(h1)
    if subtitle:
        box.addWidget(paragraph(subtitle))
    return box


def set_state_chip(chip: QLabel, state: str, text: str = "") -> None:
    """Pinta la píldora de estado de una reunión: su color, su palabra y, si lo tiene, su glifo."""
    glyph = STATE_GLYPHS.get(state)
    shown = html.escape(text or state.capitalize())
    if glyph:
        # El glifo necesita la tipografía de íconos, y la píldora usa la de texto: va en un span.
        chip.setTextFormat(Qt.TextFormat.RichText)
        chip.setText(f"<span style=\"font-family:'{T.icon_family()}'\">{glyph}</span>&nbsp; {shown}")
    else:
        chip.setTextFormat(Qt.TextFormat.PlainText)
        chip.setText(shown)
    set_tone(chip, STATE_TONES.get(state, "muted"))


def state_chip(state: str, text: str = "") -> QLabel:
    chip = label("", "chip")
    set_state_chip(chip, state, text)
    return chip


def icon_button(glyph: str, text: str = "", variant: str | None = None, tooltip: str = "") -> QPushButton:
    btn = QPushButton(text)
    # En un botón primario el glifo se queda en su color al pasar el ratón: con el de acento
    # (ICE) desaparecía sobre el relleno morado del tema Pastel.
    set_glyph_icon(btn, lambda: glyph_icon(
        glyph, color=T.ON_ACCENT if variant == "primary" else T.MUTED,
        hover=T.ON_ACCENT if variant == "primary" else T.ICE))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if variant:
        btn.setProperty("variant", variant)
    if tooltip:
        btn.setToolTip(tooltip)
    if not text:  # solo el ícono: el mismo cuadrado que el alto de un botón con texto
        btn.setFixedSize(CONTROL_H, CONTROL_H)
    elif variant == "primary":
        btn.setMinimumHeight(CONTROL_H + GAP_XS)
        add_shadow(btn, blur=14, dy=3, alpha=0.18, accent=True)
    else:
        btn.setMinimumHeight(CONTROL_H)
    return btn


def flash_check(btn: QPushButton, glyph: str) -> None:
    btn.setIcon(glyph_icon(T.Glyph.CHECK, color=T.OK, hover=T.OK))
    QTimer.singleShot(1200, lambda: btn.setIcon(glyph_icon(glyph)))


def confirm(parent: QWidget, title: str, text: str, ok_text: str) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
    box.button(QMessageBox.StandardButton.Yes).setText(ok_text)
    box.button(QMessageBox.StandardButton.Cancel).setText("Cancelar")
    return box.exec() == QMessageBox.StandardButton.Yes


def separator() -> QFrame:
    line = QFrame()
    line.setObjectName("Sep")
    line.setFixedHeight(1)
    return line


def download_text(info) -> tuple[str, str]:
    """(texto de detalle, modo de la barra) para un DownloadInfo."""
    amount = f"{fmt_bytes(info.done)} de {fmt_bytes(info.total)} · {info.fraction * 100:.0f}%" if info.total else ""
    if info.state == "connecting":
        return ("Conectando…" + (f" · {amount}" if amount else ""), "indeterminate")
    if info.state == "downloading":
        return (f"{amount} · {fmt_speed(info.speed)} · {fmt_eta(info.eta)}", "active")
    if info.state == "paused":
        return (f"En pausa · {amount}", "paused")
    if info.state == "verifying":
        return ("Verificando el archivo descargado…", "indeterminate")
    if info.state == "error":
        return (f"⚠ {info.error}" + (f" · {amount}" if amount else ""), "error")
    return ("", "paused")


# --- Inicio -------------------------------------------------------------------
def one_line(text: str, limit: int = 160) -> str:
    """Deja un texto de varias líneas en una sola, para las tarjetas del panel."""
    clean = " ".join(text.split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def fmt_minutes(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d} min"


def fmt_hours(hours: float) -> str:
    return f"{hours:.1f} h" if hours >= 1 else f"{round(hours * 60)} min"


def stat_tile(title: str) -> tuple[QFrame, QLabel]:
    """Un número grande con su etiqueta: (tarjeta, etiqueta del número)."""
    tile = card()
    tile.setFixedHeight(96)
    v = QVBoxLayout(tile)
    v.setContentsMargins(GAP_L, GAP_L, GAP_L, GAP_L)
    v.setSpacing(0)
    value = label("—", "stat")
    v.addWidget(ElidedLabel(title, "eyebrow"))
    v.addWidget(value)
    return tile, value


def panel_row(title: str, meta: str, state: str = "") -> QFrame:
    """Una línea dentro de una tarjeta del panel: texto, datos y, si aplica, su estado."""
    row = QFrame()
    row.setObjectName("Row")
    h = QHBoxLayout(row)
    h.setContentsMargins(GAP_S, GAP_S, GAP_S, GAP_S)
    h.setSpacing(GAP_M)
    texts = QVBoxLayout()
    texts.setSpacing(GAP_XS)
    head = ElidedLabel(title)
    head.setProperty("role", "title")
    texts.addWidget(head)
    texts.addWidget(ElidedLabel(meta, "dim"))
    h.addLayout(texts, 1)
    if state:
        h.addWidget(state_chip(state), 0, Qt.AlignmentFlag.AlignVCenter)
    return row


class PanelCard(ClickCard):
    """Tarjeta del panel: encabezado, filas y «ver todo». El clic lleva a su pestaña."""

    def __init__(self, glyph: str, title: str, hint: str, on_open) -> None:
        super().__init__()
        self._glyph = glyph
        self.setMinimumHeight(212)
        # El margen de la tarjeta más la sangría de las filas suman el relleno de siempre: así el
        # ícono del encabezado y los títulos de las filas caen en la misma vertical.
        v = QVBoxLayout(self)
        v.setContentsMargins(GAP_M, T.CARD_PAD, GAP_M, T.CARD_PAD)
        v.setSpacing(GAP_M)
        head = QHBoxLayout()
        head.setSpacing(GAP_M)
        head.setContentsMargins(GAP_S, 0, GAP_S, 0)
        head.addWidget(GlyphLabel(glyph, "CYAN", 18))
        # El título manda: en una tarjeta angosta «Reuniones» se cortaba a media palabra porque
        # Qt repartía el ancho con el «ver todas». Ese es un adorno (la tarjeta entera es un botón),
        # así que se encoge él y, si hace falta, desaparece.
        head_title = label(title, "h2")
        head_title.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        head.addWidget(head_title)
        head.addStretch(1)
        head_hint = ElidedLabel(hint, "mini")
        head_hint.setMinimumWidth(0)
        head.addWidget(head_hint)
        v.addLayout(head)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(GAP_XS)
        v.addLayout(self.rows)
        v.addStretch(1)
        self.clicked.connect(on_open)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self._shadow(12, 2)  # al presionar, la tarjeta se apoya en el fondo

    def mouseReleaseEvent(self, event):
        self._shadow(24, 6)  # al soltar sigue bajo el ratón: vuelve a la sombra de hover
        super().mouseReleaseEvent(event)

    def _shadow(self, blur: int, dy: int) -> None:
        effect = self.graphicsEffect()
        if effect is not None:
            effect.setBlurRadius(blur)
            effect.setOffset(0, dy)

    def fill(self, rows: list[QFrame], empty: str) -> None:
        while self.rows.count():
            item = self.rows.takeAt(0)
            old = item.widget()
            if old is not None:
                old.setParent(None)  # sin esto se sigue viendo hasta que Qt lo borra
                old.deleteLater()
        if not rows:
            self.rows.addWidget(empty_state(self._glyph, empty, compact=True))
        for row in rows:
            self.rows.addWidget(row)


class HomePage(QWidget):
    """Panel de control: qué está pasando, qué grabaste y los accesos rápidos."""

    def __init__(self, ctl: "Controller"):
        super().__init__()
        self.ctl = ctl
        self._last = ""
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setContentsMargins(T.PAGE_MARGIN, T.PAGE_TOP, T.PAGE_MARGIN - SCROLL_GUTTER, T.PAGE_BOTTOM)
        root.setSpacing(T.SECTION_GAP)
        root.addLayout(page_header(
            "TODO EN TU PC · WHISPER",
            "Tu panel",
            "Dicta con tu atajo en cualquier app, graba tus reuniones y revisa aquí lo que ya quedó guardado.",
        ))

        hero = QHBoxLayout()
        hero.setSpacing(T.CARD_GAP)
        root.addLayout(hero)
        hero.addWidget(self._dictation_card(), 5)
        side_host = QWidget()
        side_host.setMaximumWidth(380)  # en pantallas anchas la columna no se estira
        side_host.setLayout(self._side_column())
        hero.addWidget(side_host, 4)
        root.addWidget(self._stats_row())

        # Tarjetas clicables: cada una lleva a su pestaña.
        panels_host = QWidget()
        panels = CardFlow(250, T.CARD_GAP, panels_host)
        panels.setContentsMargins(0, 0, 0, SHADOW_ROOM)  # aire para la sombra de la última fila
        self.meetings_card = PanelCard(T.Glyph.MEETING, "Reuniones", "VER TODAS  ›", lambda: self._go(2))
        self.notes_card = PanelCard(T.Glyph.PASTE, "Tus notas", "ABRIR  ›", lambda: self._go(2))
        self.dictations_card = PanelCard(T.Glyph.HISTORY, "Dictados", "VER TODOS  ›", lambda: self._go(1))
        for panel in (self.meetings_card, self.notes_card, self.dictations_card):
            panels.addWidget(panel)
        root.addWidget(panels_host)
        root.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrollable(inner))
        self.refresh()

    # --- piezas del panel -----------------------------------------------------
    def _dictation_card(self) -> QFrame:
        ctl = self.ctl
        mic_card = card(glow=True)
        mic_card.setObjectName("Hero")  # radio más generoso que el resto de tarjetas
        mic = QVBoxLayout(mic_card)
        mic.setContentsMargins(T.CARD_PAD, T.CARD_PAD, T.CARD_PAD, T.CARD_PAD)
        mic.setSpacing(GAP_S)
        level = lambda: ctl.recorder.level  # noqa: E731
        self.orb = MicOrb(level)
        self.orb.setMinimumSize(160, 176)
        self.orb.setMaximumHeight(260)  # crece un poco en pantallas grandes, sin comerse el panel
        self.orb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.orb.clicked.connect(ctl.toggle_recording)
        self.status = QLabel("Cargando Whisper…")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setProperty("role", "status")
        add_glow(self.status, blur=22, alpha=0.45)
        self.bars = WaveBars(level, height=WAVE_H)
        hot = QHBoxLayout()
        hot.addStretch(1)
        self.keycaps = KeyCaps(ctl.settings.hotkey)
        hot.addWidget(self.keycaps)
        hot.addStretch(1)
        self.mode_label = label(mode_hint(ctl.settings.mode), "muted", wrap=True)
        self.mode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dictate_btn = QPushButton("Dictar ahora")
        self.dictate_btn.setProperty("variant", "hero")
        self.dictate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dictate_btn.clicked.connect(ctl.toggle_recording)
        add_shadow(self.dictate_btn, blur=14, dy=3, alpha=0.18, accent=True)
        # Los stretch dejan el orbe centrado y el botón siempre abajo, sin huecos raros en medio.
        mic.addStretch(1)
        mic.addWidget(self.orb)
        mic.addWidget(self.status)
        mic.addWidget(self.bars)
        mic.addSpacing(GAP_S)
        mic.addLayout(hot)
        mic.addWidget(self.mode_label)
        mic.addStretch(1)
        mic.addWidget(self.dictate_btn)
        return mic_card

    def _side_column(self) -> QVBoxLayout:
        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(T.CARD_GAP)

        meeting_card = card()
        mv = QVBoxLayout(meeting_card)
        mv.setContentsMargins(T.CARD_PAD, T.CARD_PAD, T.CARD_PAD, T.CARD_PAD)
        mv.setSpacing(GAP_M)
        head = QHBoxLayout()
        head.setSpacing(GAP_M)
        head.addWidget(GlyphLabel(T.Glyph.MEETING, "CYAN", 18))
        head.addWidget(label("Reuniones", "h2"))
        head.addStretch(1)
        mv.addLayout(head)
        self.meeting_hint = label("", "muted", wrap=True)
        mv.addWidget(self.meeting_hint)
        self.meeting_btn = QPushButton("Grabar reunión")
        self.meeting_btn.setProperty("variant", "hero2")
        self.meeting_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.meeting_btn.clicked.connect(self.ctl.toggle_meeting)
        mv.addWidget(self.meeting_btn)
        side.addWidget(meeting_card)

        last = card()
        lv = QVBoxLayout(last)
        lv.setContentsMargins(T.CARD_PAD, T.CARD_PAD, T.CARD_PAD, T.CARD_PAD)
        lv.setSpacing(GAP_M)
        top = QHBoxLayout()
        top.addWidget(label("ÚLTIMA TRANSCRIPCIÓN", "eyebrow"))
        top.addStretch(1)
        self.copy_last = icon_button(T.Glyph.COPY, variant="ghost", tooltip="Copiar")
        self.copy_last.clicked.connect(self._copy_last)
        top.addWidget(self.copy_last)
        lv.addLayout(top)
        self.last_text = label("Todavía no has dictado nada. Prueba tu atajo o haz clic en el micrófono.",
                               "muted", wrap=True)
        self.last_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.last_text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.last_text.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        lv.addWidget(self.last_text, 1)
        side.addWidget(last, 1)
        return side

    def _stats_row(self) -> QWidget:
        host = QWidget()
        tiles = CardFlow(138, T.CARD_GAP, host)
        tiles.setContentsMargins(0, 0, 0, SHADOW_ROOM)  # aire para la sombra
        self.tiles: dict[str, QLabel] = {}
        for key, title in (("dictados", "DICTADOS"), ("palabras", "PALABRAS"),
                           ("reuniones", "REUNIONES"), ("tiempo", "TIEMPO GRABADO")):
            tile, value = stat_tile(title)
            self.tiles[key] = value
            tiles.addWidget(tile)
        return host

    # --- datos ----------------------------------------------------------------
    def refresh(self) -> None:
        """Vuelve a leer reuniones, notas y dictados. Se llama al entrar a la pestaña."""
        # list_brief no arrastra transcripciones enteras: el panel solo necesita títulos y notas.
        store = self.ctl.meetings
        meetings = (store.list_brief if hasattr(store, "list_brief") else store.list)(limit=20)
        rows = []
        for meeting in meetings[:4]:
            meta = f"{human_date(meeting.created_at)}   ·   {fmt_minutes(meeting.duration)}"
            rows.append(panel_row(meeting.label, meta, meeting.state))
        self.meetings_card.fill(rows, "Todavía no grabas ninguna reunión. Dale a «Grabar reunión» "
                                      "o actívalas en Ajustes.")

        notes = []
        for meeting in meetings:
            if meeting.notes.strip():
                notes.append(panel_row(one_line(meeting.notes), f"{meeting.label}   ·   "
                                                                f"{human_date(meeting.created_at)}"))
            if len(notes) == 4:
                break
        self.notes_card.fill(notes, "Lo que anotes durante una reunión se guarda con ella y aparece aquí.")

        entries = self.ctl.history.list(limit=4)
        rows = [panel_row(one_line(e.text), f"{human_date(e.created_at)}   ·   {len(e.text.split())} palabras")
                for e in entries]
        self.dictations_card.fill(rows, "Aquí van tus últimos dictados. Prueba tu atajo en cualquier app.")

        count, hours = self.ctl.meetings.stats()
        self.tiles["reuniones"].setText(f"{count:,}")
        self.tiles["tiempo"].setText(fmt_hours(hours))
        self._update_meeting_hint()

    def _update_meeting_hint(self) -> None:
        recording = self.ctl.meeting_recorder.recording
        self.meeting_btn.setText("Detener la reunión" if recording else "Grabar reunión")
        if recording:
            text = f"Grabando {self.ctl.meeting_recorder.describe()}. Al terminar la transcribo y la resumo."
        elif self.ctl.settings.meetings_enabled:
            text = "Detecto cuando entras a una junta y te aviso. Al terminar dejo transcripción y resumen."
        else:
            text = "Puedes grabar una junta cuando quieras. Para que se detecten solas, actívalo en Ajustes."
        self.meeting_hint.setText(text)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def _go(self, index: int) -> None:
        self.ctl.window.go_to(index)

    # --- lo que llama el controlador -----------------------------------------
    def set_state(self, state: str, text: str) -> None:
        self.orb.set_state(state)
        self.bars.set_mode({"recording": "recording", "processing": "processing"}.get(state, "idle"))
        self.status.setText(text)
        self.dictate_btn.setText("Detener y pegar" if state == "recording" else "Dictar ahora")
        self.dictate_btn.setEnabled(state != "disabled")
        self._update_meeting_hint()

    def set_last(self, text: str) -> None:
        self._last = text
        self.last_text.setText(text)
        self.last_text.setProperty("role", "body")
        repolish(self.last_text)

    def set_stats(self, count: int, words: int, seconds: float | None) -> None:
        self.tiles["dictados"].setText(f"{count:,}")
        self.tiles["palabras"].setText(f"{words:,}")
        if self.isVisible():
            self.refresh()

    def set_hotkey(self, hotkey: str, mode: str) -> None:
        self.keycaps.set_hotkey(hotkey)
        self.mode_label.setText(mode_hint(mode))

    def _copy_last(self) -> None:
        if self._last:
            self.ctl.paster.copy(self._last)
            flash_check(self.copy_last, T.Glyph.COPY)


# --- Historial ----------------------------------------------------------------
class EntryCard(QFrame):
    def __init__(self, entry: Entry, ctl: "Controller"):
        super().__init__()
        self.setObjectName("Card")
        self.setMinimumHeight(88)
        add_shadow(self)  # la misma sombra suave que el resto de tarjetas de la app
        self.entry, self.ctl = entry, ctl
        v = QVBoxLayout(self)
        v.setContentsMargins(T.CARD_PAD, T.CARD_PAD, ACTION_EDGE, T.CARD_PAD)
        v.setSpacing(GAP_S)
        top = QHBoxLayout()
        words = len(entry.text.split())
        meta = f"{human_date(entry.created_at)}   ·   {entry.duration:.0f} s   ·   {words} palabra{'s' if words != 1 else ''}"
        top.addWidget(ElidedLabel(meta, "dim"))
        top.addStretch(1)
        self.copy_btn = icon_button(T.Glyph.COPY, variant="ghost", tooltip="Copiar")
        self.copy_btn.clicked.connect(self._copy)
        delete = icon_button(T.Glyph.DELETE, variant="ghost", tooltip="Borrar")
        delete.clicked.connect(lambda: ctl.delete_entry(entry.id))
        top.addWidget(self.copy_btn)
        top.addWidget(delete)
        v.addLayout(top)
        text = QLabel(entry.text)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.setProperty("role", "body")
        v.addWidget(text)

    def _copy(self) -> None:
        self.ctl.paster.copy(self.entry.text)
        flash_check(self.copy_btn, T.Glyph.COPY)


class HistoryPage(QWidget):
    def __init__(self, ctl: "Controller"):
        super().__init__()
        self.ctl = ctl
        root = page_body(self)
        root.setContentsMargins(T.PAGE_MARGIN, T.PAGE_TOP, T.PAGE_MARGIN - SCROLL_GUTTER, T.PAGE_BOTTOM)
        root.setSpacing(T.SECTION_GAP)

        head = QHBoxLayout()
        head.setSpacing(GAP_L)
        head.addLayout(page_header("TUS DICTADOS", "Historial",
                                   "Todo lo que dictas con tu atajo se guarda aquí, en tu PC."), 1)
        export = icon_button(T.Glyph.EXPORT, "Exportar")
        export.clicked.connect(self._export)
        clear = icon_button(T.Glyph.CLEAR, "Borrar todo", variant="danger")
        clear.clicked.connect(self._clear)
        head.addWidget(export, 0, Qt.AlignmentFlag.AlignBottom)
        head.addWidget(clear, 0, Qt.AlignmentFlag.AlignBottom)
        root.addLayout(head)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar en tu historial…")
        readable_hint(self.search)
        search_icon = self.search.addAction(glyph_icon(T.Glyph.SEARCH), QLineEdit.ActionPosition.LeadingPosition)
        on_restyle(self.search, lambda: search_icon.setIcon(glyph_icon(T.Glyph.SEARCH)))
        self.search.setClearButtonEnabled(True)
        self._debounce = QTimer(self, singleShot=True, interval=180, timeout=self.refresh)
        self.search.textChanged.connect(self._debounce.start)
        root.addWidget(self.search)

        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 0, SHADOW_ROOM)
        self.list_layout.setSpacing(T.CARD_GAP)
        root.addWidget(scrollable(self.list_host), 1)
        self.refresh()

    def refresh(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            old = item.widget()
            if old is not None:
                old.setParent(None)  # sin esto se sigue viendo hasta que Qt lo borra
                old.deleteLater()
        query = self.search.text().strip()
        entries = self.ctl.history.list(query, limit=300)
        if not entries:
            self.list_layout.addWidget(empty_state(
                T.Glyph.SEARCH if query else T.Glyph.MIC,
                "No hay resultados para tu búsqueda." if query else
                "Aquí aparecerá todo lo que dictes. Presiona tu atajo en cualquier app y habla."))
        for entry in entries:
            self.list_layout.addWidget(EntryCard(entry, self.ctl))
        self.list_layout.addStretch(1)

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar historial", str(os.path.expanduser("~/Documents/NeonWhisper-historial.txt")), "Texto (*.txt)"
        )
        if not path:
            return
        entries = self.ctl.history.list(limit=1_000_000)
        with open(path, "w", encoding="utf-8") as f:
            for e in reversed(entries):
                f.write(f"[{e.created_at}]\n{e.text}\n\n")

    def _clear(self) -> None:
        if confirm(self, "Borrar historial", "¿Borrar todo el historial? Esta acción no se puede deshacer.", "Borrar todo"):
            self.ctl.clear_history()


# --- Reuniones ----------------------------------------------------------------
def summary_html(text: str) -> str:
    """El resumen viene en markdown sencillo (## títulos y viñetas): se pinta como texto con formato."""
    lines = ["<div style='line-height:140%'>"]
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            lines.append("<br>")
        elif line.startswith("#"):
            # Mismo aspecto que un rótulo «eyebrow»: Bahnschrift no está en la pila de la app y
            # dejaba los títulos del resumen con una letra distinta a la de toda la interfaz.
            title = line.lstrip("#").strip().upper()
            lines.append(f"<div style='color:{T.CYAN}; font-family:{T.FONT_DISPLAY}; font-size:8.5pt; "
                         f"font-weight:600; letter-spacing:1.6px; margin-top:{GAP_M}px;'>{title}</div>")
        elif line.startswith(("-", "*", "•")):
            lines.append(f"<div style='margin-left:{GAP_XS}px;'>•&nbsp; {line.lstrip('-*• ')}</div>")
        else:
            lines.append(f"<div>{line}</div>")
    return "".join(lines) + "</div>"


class MeetingCard(QFrame):
    """Una reunión en la lista: cabecera con datos y, al desplegarla, resumen y transcripción."""

    def __init__(self, meeting, ctl: "Controller"):
        super().__init__()
        self.setObjectName("Card")
        self.setMinimumHeight(88)
        add_shadow(self)  # la misma sombra suave que el resto de tarjetas de la app
        self.meeting, self.ctl = meeting, ctl
        self.open = False
        v = QVBoxLayout(self)
        v.setContentsMargins(T.CARD_PAD, T.CARD_PAD, ACTION_EDGE, T.CARD_PAD)
        v.setSpacing(GAP_M)

        self._compact = False
        self._selecting = False

        top = QHBoxLayout()
        top.setSpacing(GAP_M)
        # La casilla solo sale en modo selección: el resto del tiempo la tarjeta se ve igual que siempre.
        self.check = QCheckBox()
        self.check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check.setEnabled(meeting.state != "grabando")
        self.check.setToolTip("Marcar esta reunión" if self.check.isEnabled()
                              else "No se puede borrar una reunión que se está grabando")
        if not self.check.isEnabled():
            # Apagada se ve igual que sin marcar: se atenúa para que se note que no se puede.
            faded = QGraphicsOpacityEffect(self.check)
            faded.setOpacity(0.35)
            self.check.setGraphicsEffect(faded)
        self.check.hide()
        top.addWidget(self.check, 0, Qt.AlignmentFlag.AlignVCenter)
        titles = QVBoxLayout()
        titles.setSpacing(GAP_XS)
        titles.addWidget(ElidedLabel(meeting.label, "title"))
        minutes = meeting.duration / 60
        meta = f"{human_date(meeting.created_at)}   ·   {minutes:.0f} min   ·   {meeting.words} palabras"
        titles.addWidget(ElidedLabel(meta, "dim"))
        if meeting.error:
            reason = paragraph(meeting.error)
            set_tone(reason, "danger")
            titles.addWidget(reason)
        top.addLayout(titles, 1)

        # La misma píldora que en el panel de inicio: un estado, un color, un glifo, el mismo tamaño.
        self.state = state_chip(meeting.state)
        top.addWidget(self.state, 0, Qt.AlignmentFlag.AlignVCenter)

        self.toggle = icon_button(T.Glyph.HISTORY, "Ver", variant="ghost", tooltip="Resumen y transcripción")
        self.toggle.clicked.connect(self._toggle)
        copy_btn = icon_button(T.Glyph.COPY, variant="ghost", tooltip="Copiar el resumen")
        copy_btn.clicked.connect(self._copy)
        export = icon_button(T.Glyph.EXPORT, variant="ghost", tooltip="Guardar como .txt")
        export.clicked.connect(self._export)
        delete = icon_button(T.Glyph.DELETE, variant="ghost", tooltip="Borrar la reunión")
        delete.clicked.connect(self._delete)
        top.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        self.extra = [copy_btn, export, delete]
        actions = [("Copiar el resumen", self._copy), ("Guardar como .txt", self._export),
                   ("Borrar la reunión", self._delete)]
        if meeting.state == "error" or (meeting.state == "lista" and not meeting.summary):
            retry = icon_button(T.Glyph.RETRY, variant="ghost", tooltip="Reintentar")
            retry.clicked.connect(lambda: ctl.retry_meeting(meeting.id))
            self.extra.append(retry)
            actions.append(("Reintentar", lambda: ctl.retry_meeting(meeting.id)))
        for b in self.extra:
            top.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        # En la ventana angosta los iconos no caben: se guardan aquí y no se pierde ninguna acción.
        self.more = QPushButton("···")
        self.more.setProperty("variant", "ghost")
        self.more.setFixedSize(CONTROL_H, CONTROL_H)
        self.more.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more.setToolTip("Más acciones")
        menu = QMenu(self.more)
        for text, slot in actions:
            menu.addAction(text, slot)
        self.more.setMenu(menu)
        self.more.hide()
        top.addWidget(self.more, 0, Qt.AlignmentFlag.AlignVCenter)
        v.addLayout(top)

        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, GAP_L, 0, 0)
        body.setSpacing(GAP_XS)
        if meeting.summary:
            summary = QLabel()  # texto enriquecido propio: no pasa por WrapLabel
            summary.setWordWrap(True)
            summary.setProperty("role", "body")
            summary.setTextFormat(Qt.TextFormat.RichText)
            on_restyle(summary, lambda text=meeting.summary: summary.setText(summary_html(text)))
            summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            body.addWidget(summary)
            body.addSpacing(GAP_S)
        body.addWidget(label("TUS NOTAS", "eyebrow"))
        self.notes = QPlainTextEdit(meeting.notes)
        self.notes.setPlaceholderText("Lo que anotaste en la reunión. Puedes seguir escribiendo aquí.")
        self.notes.setMinimumHeight(88)
        self.notes.setMaximumHeight(200)
        self.notes.textChanged.connect(self._save_notes)
        body.addWidget(self.notes)
        body.addSpacing(GAP_S)
        body.addWidget(label("TRANSCRIPCIÓN", "eyebrow"))
        text = QPlainTextEdit(meeting.transcript or "Sin transcripción.")
        text.setReadOnly(True)
        text.setMinimumHeight(180)
        body.addWidget(text)
        self.body.hide()
        v.addWidget(self.body)

    def set_compact(self, compact: bool) -> None:
        self._compact = compact
        self._apply_actions()

    def set_selecting(self, selecting: bool) -> None:
        """En modo selección aparece la casilla y se guardan las acciones de una sola reunión."""
        self._selecting = selecting
        self.check.setVisible(selecting)
        if not selecting:
            self.check.setChecked(False)
        elif self.open:
            self._toggle()  # desplegada estorba: se cierra al entrar al modo
        self._apply_actions()

    def _apply_actions(self) -> None:
        show = not self._selecting
        self.toggle.setVisible(show)
        for b in self.extra:
            b.setVisible(show and not self._compact)
        self.more.setVisible(show and self._compact)

    def mouseReleaseEvent(self, event):
        # Eligiendo varias, el clic en cualquier parte de la tarjeta la marca o la desmarca.
        if self._selecting and self.check.isEnabled() and event.button() == Qt.MouseButton.LeftButton:
            self.check.setChecked(not self.check.isChecked())
        super().mouseReleaseEvent(event)

    def _toggle(self) -> None:
        self.open = not self.open
        self.body.setVisible(self.open)
        self.toggle.setText("Ocultar" if self.open else "Ver")

    def _save_notes(self) -> None:
        """Las notas se guardan solas, medio segundo después de dejar de escribir."""
        if not hasattr(self, "_notes_timer"):
            self._notes_timer = QTimer(self, singleShot=True, interval=600)
            self._notes_timer.timeout.connect(
                lambda: self.ctl.meetings.update(self.meeting.id, notes=self.notes.toPlainText()))
        self._notes_timer.start()

    def _copy(self) -> None:
        self.ctl.paster.copy(self.meeting.summary or self.meeting.transcript)
        flash_check(self.toggle, T.Glyph.HISTORY)

    def _export(self) -> None:
        name = f"reunion-{self.meeting.created_at[:10]}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar la reunión", str(os.path.expanduser(f"~/Documents/{name}")), "Texto (*.txt)")
        if not path:
            return
        parts = [f"{self.meeting.label} · {self.meeting.created_at} · {self.meeting.duration / 60:.0f} min"]
        if self.meeting.summary:
            parts += ["", "RESUMEN", self.meeting.summary]
        parts += ["", "TRANSCRIPCIÓN", self.meeting.transcript]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(parts))

    def _delete(self) -> None:
        if confirm(self, "Borrar reunión", f"¿Borrar «{self.meeting.label}» y su transcripción?", "Borrar"):
            self.ctl.delete_meeting(self.meeting.id)


class MeetingsPage(QWidget):
    def __init__(self, ctl: "Controller"):
        super().__init__()
        self.ctl = ctl
        self.cards: dict[int, MeetingCard] = {}
        self._selecting = False
        self._selected: set[int] = set()
        root = page_body(self)
        root.setContentsMargins(T.PAGE_MARGIN, T.PAGE_TOP, T.PAGE_MARGIN - SCROLL_GUTTER, T.PAGE_BOTTOM)
        root.setSpacing(T.SECTION_GAP)

        head = QHBoxLayout()
        head.setSpacing(GAP_L)
        head.addLayout(page_header(
            "GRABADAS EN TU PC", "Reuniones",
            "NeonWhisper detecta cuándo entras a una reunión, la graba y al terminar te deja la "
            "transcripción y un resumen."), 1)
        self.record_btn = icon_button(T.Glyph.MIC, "Grabar ahora", variant="primary")
        self.record_btn.clicked.connect(ctl.toggle_meeting)
        head.addWidget(self.record_btn, 0, Qt.AlignmentFlag.AlignBottom)
        root.addLayout(head)

        # Tarjeta de la reunión en curso.
        self.live = card(glow=True)
        live_box = QVBoxLayout(self.live)
        live_box.setContentsMargins(T.CARD_PAD, T.CARD_PAD, T.CARD_PAD, T.CARD_PAD)
        live_box.setSpacing(GAP_L)
        live_row = QWidget()
        live = QHBoxLayout(live_row)
        live.setContentsMargins(0, 0, 0, 0)
        live.setSpacing(GAP_L)
        live_box.addWidget(live_row)
        self.live_dot = StatusDot()
        self.live_dot.state = "recording"
        live.addWidget(self.live_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(GAP_XS)
        self.live_title = ElidedLabel("Grabando reunión", "title")
        self.live_detail = ElidedLabel("", "dim")
        texts.addWidget(self.live_title)
        texts.addWidget(self.live_detail)
        live.addLayout(texts, 1)
        self.live_bars = WaveBars(lambda: ctl.meeting_recorder.level, height=WAVE_H)
        live.addWidget(self.live_bars, 1)

        # Qué se está grabando: se puede silenciar cada fuente en caliente.
        self.source_buttons: dict[str, QPushButton] = {}
        picker = QWidget()
        pl = QHBoxLayout(picker)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        self.source_names = {"mic": ("Mi voz", "Voz"), "system": ("Los demás", "Sistema")}
        for pos, (kind, text, glyph) in enumerate((("mic", "Mi voz", T.Glyph.MIC),
                                                   ("system", "Los demás", T.Glyph.VOLUME))):
            b = QPushButton(f" {text}")
            b.setObjectName("Segment")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setProperty("pos", "first" if pos == 0 else "last")
            set_glyph_icon(b, lambda g=glyph, k=kind: glyph_icon(
                g, color=T.MUTED, checked=T.ON_ACCENT))
            b.clicked.connect(lambda checked, k=kind: ctl.mute_meeting_source(k, not checked))
            self.source_buttons[kind] = b
            pl.addWidget(b)
        live.addWidget(picker, 0, Qt.AlignmentFlag.AlignVCenter)
        stop = icon_button(T.Glyph.PAUSE, "Detener")
        stop.clicked.connect(ctl.toggle_meeting)
        live.addWidget(stop, 0, Qt.AlignmentFlag.AlignVCenter)

        # Debajo: lo que se va transcribiendo y un bloc para tus notas.
        self.panel = QGridLayout()
        self.panel.setSpacing(GAP_L)
        transcript_host = QWidget()
        transcript_box = QVBoxLayout(transcript_host)
        transcript_box.setContentsMargins(0, 0, 0, 0)
        transcript_box.setSpacing(GAP_XS)
        transcript_box.addWidget(label("EN VIVO", "eyebrow"))
        self.live_view = QPlainTextEdit()
        self.live_view.setReadOnly(True)
        self.live_view.setMinimumHeight(120)
        self.live_view.setMaximumHeight(260)
        self.live_view.setPlaceholderText("La transcripción aparecerá aquí cada ~30 segundos…")
        transcript_box.addWidget(self.live_view)
        notes_host = QWidget()
        notes_box = QVBoxLayout(notes_host)
        notes_box.setContentsMargins(0, 0, 0, 0)
        notes_box.setSpacing(GAP_XS)
        notes_box.addWidget(label("TUS NOTAS", "eyebrow"))
        self.notes_view = QPlainTextEdit()
        self.notes_view.setMinimumHeight(120)
        self.notes_view.setMaximumHeight(260)
        self.notes_view.setPlaceholderText("Apunta lo que importa: entra en el resumen final.")
        self.notes_view.textChanged.connect(lambda: ctl.set_meeting_notes(self.notes_view.toPlainText()))
        notes_box.addWidget(self.notes_view)
        self._panel_hosts = (transcript_host, notes_host)
        live_box.addLayout(self.panel)
        self._compact = None
        self.set_compact(False)
        self.live.hide()
        content = QWidget()
        stack = QVBoxLayout(content)
        stack.setContentsMargins(0, 0, 0, SHADOW_ROOM)
        stack.setSpacing(T.SECTION_GAP)
        stack.addWidget(self.live)
        root.addWidget(scrollable(content, limit=False), 1)
        self._clock = QTimer(self, interval=1000, timeout=self._tick)

        # Preguntar a tus reuniones, con el modelo local.
        self.ask_card = card()
        ask_box = QVBoxLayout(self.ask_card)
        ask_box.setContentsMargins(T.CARD_PAD, T.CARD_PAD, T.CARD_PAD, T.CARD_PAD)
        ask_box.setSpacing(GAP_M)
        ask_row = QHBoxLayout()
        ask_row.setSpacing(GAP_M)
        self.ask_input = QLineEdit()
        self.ask_input.setPlaceholderText("Pregúntale a tus reuniones: «¿qué quedó pendiente para mí?»")
        readable_hint(self.ask_input)
        self.ask_input.returnPressed.connect(self._ask)
        ask_btn = icon_button(T.Glyph.BOLT, "Preguntar", variant="primary")
        ask_btn.clicked.connect(self._ask)
        ask_row.addWidget(self.ask_input, 1)
        ask_row.addWidget(ask_btn)
        ask_box.addLayout(ask_row)
        self.answer = paragraph()
        self.answer.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.answer.hide()
        ask_box.addWidget(self.answer)
        stack.addWidget(self.ask_card)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar en tus reuniones…")
        readable_hint(self.search)
        search_icon = self.search.addAction(glyph_icon(T.Glyph.SEARCH), QLineEdit.ActionPosition.LeadingPosition)
        on_restyle(self.search, lambda: search_icon.setIcon(glyph_icon(T.Glyph.SEARCH)))
        self.search.setClearButtonEnabled(True)
        self._debounce = QTimer(self, singleShot=True, interval=180, timeout=self.refresh)
        self.search.textChanged.connect(self._debounce.start)
        search_row = QWidget()
        sr = QHBoxLayout(search_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.setSpacing(GAP_M)
        sr.addWidget(self.search, 1)
        self.select_btn = icon_button(T.Glyph.CHECK, "Seleccionar",
                                      tooltip="Elegir varias reuniones para borrarlas de golpe")
        self.select_btn.clicked.connect(lambda: self._set_selecting(not self._selecting))
        sr.addWidget(self.select_btn)
        stack.addWidget(search_row)

        # Barra de selección: solo está cuando la usas, para no cargar la página el resto del tiempo.
        self.select_bar = card(glow=True)
        sb = QHBoxLayout(self.select_bar)
        sb.setContentsMargins(T.CARD_PAD, GAP_M, T.CARD_PAD, GAP_M)  # es una barra, no una tarjeta de contenido
        sb.setSpacing(GAP_M)
        self.select_count = ElidedLabel("", "title")
        sb.addWidget(self.select_count, 1)
        all_btn = icon_button(T.Glyph.CHECK, "Todas", variant="ghost", tooltip="Marcar todas las de la lista")
        all_btn.clicked.connect(self._select_all)
        none_btn = icon_button(T.Glyph.CLEAR, "Ninguna", variant="ghost", tooltip="Quitar la selección")
        none_btn.clicked.connect(self._select_none)
        self.delete_selected = icon_button(T.Glyph.DELETE, "Borrar", variant="danger",
                                           tooltip="Borrar las reuniones marcadas")
        self.delete_selected.clicked.connect(self._delete_selected)
        for b in (all_btn, none_btn, self.delete_selected):
            sb.addWidget(b)
        self.select_bar.hide()
        stack.addWidget(self.select_bar)

        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(T.CARD_GAP)
        stack.addWidget(self.list_host)
        stack.addStretch(1)
        self.refresh()

    # --- ventana angosta -----------------------------------------------------
    def set_compact(self, compact: bool) -> None:
        """Con poco ancho: el panel en vivo se apila, el segmento se acorta y los iconos se esconden."""
        if compact == self._compact:
            return
        self._compact = compact
        transcript_host, notes_host = self._panel_hosts
        self.panel.removeWidget(transcript_host)
        self.panel.removeWidget(notes_host)
        self.panel.addWidget(transcript_host, 0, 0)
        self.panel.addWidget(notes_host, 1, 0) if compact else self.panel.addWidget(notes_host, 0, 1)
        self.live_bars.setVisible(not compact)
        for kind, button in self.source_buttons.items():
            button.setText(f" {self.source_names[kind][1 if compact else 0]}")
        for card_widget in self.cards.values():
            card_widget.set_compact(compact)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.set_compact(self.width() < COMPACT_WIDTH)

    # --- reunión en curso ----------------------------------------------------
    def set_live(self, recorder, meeting) -> None:
        active = recorder.recording
        self.live.setVisible(active)
        self.record_btn.setText("Detener" if active else "Grabar ahora")
        self.live_bars.set_mode("recording" if active else "idle")
        sources = recorder.sources if active else {}
        for kind, button in self.source_buttons.items():
            available = active and (kind == "mic" or recorder.system_audio)
            button.setEnabled(available)
            button.setChecked(bool(sources.get(kind)))
            button.setToolTip("" if available else "Windows no expone un dispositivo «loopback» en esta PC")
            repolish(button)
        if active and not self._clock.isActive():  # empieza una reunión: panel limpio
            self.live_view.setPlainText(" ".join(self.ctl.live_text))
            self.notes_view.blockSignals(True)
            self.notes_view.setPlainText(meeting.notes if meeting else "")
            self.notes_view.blockSignals(False)
            self.live_view.setVisible(self.ctl.settings.meeting_live_transcript)
        if active:
            self.live_title.setText(f"Grabando · {meeting.label if meeting else 'reunión'}")
            self._recorder = recorder
            self._tick()
            if not self._clock.isActive():
                self._clock.start()
        else:
            self._clock.stop()

    def append_live(self, text: str) -> None:
        """Añade el último tramo transcrito mientras la reunión sigue."""
        if not text:
            return
        self.live_view.setPlainText((self.live_view.toPlainText() + " " + text).strip())
        bar = self.live_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _ask(self) -> None:
        question = self.ask_input.text().strip()
        if question:
            self.ctl.ask_meetings(question)

    def show_answer(self, question: str, answer: str, error: str) -> None:
        """Respuesta del modelo local (o el estado de «pensando…»)."""
        if error:
            text, tone = error, "danger"
        elif answer:
            text, tone = answer, "muted"
        else:
            text, tone = f"Pensando en «{question[:60]}»…", "accent"
        self.answer.setText(text)
        set_tone(self.answer, tone)
        self.answer.show()

    def _tick(self) -> None:
        recorder = getattr(self, "_recorder", None)
        if recorder is None or not recorder.recording:
            return
        secs = int(recorder.elapsed)
        self.live_detail.setText(f"{secs // 60}:{secs % 60:02d}   ·   grabando {recorder.describe()}")

    def set_progress(self, meeting_id: int, text: str) -> None:
        card_widget = self.cards.get(meeting_id)
        if card_widget is not None:
            set_state_chip(card_widget.state, "transcribiendo", text)

    # --- elegir varias y borrarlas de golpe ----------------------------------
    def _set_selecting(self, on: bool) -> None:
        self._selecting = on
        self.select_btn.setText("Listo" if on else "Seleccionar")
        self.select_bar.setVisible(on)
        self._selected.clear()
        for card_widget in self.cards.values():
            card_widget.set_selecting(on)
        self._update_selection()

    def _on_check(self, meeting_id: int, checked: bool) -> None:
        if checked:
            self._selected.add(meeting_id)
        else:
            self._selected.discard(meeting_id)
        self._update_selection()

    def _update_selection(self) -> None:
        count = len(self._selected)
        self.select_count.setText(
            "Ninguna seleccionada" if not count else
            "1 reunión seleccionada" if count == 1 else f"{count} reuniones seleccionadas")
        self.delete_selected.setText(f"Borrar {count}" if count else "Borrar")
        self.delete_selected.setEnabled(bool(count))

    def _select_all(self) -> None:
        for card_widget in self.cards.values():
            if card_widget.check.isEnabled():  # la que se está grabando, no
                card_widget.check.setChecked(True)

    def _select_none(self) -> None:
        for card_widget in self.cards.values():
            card_widget.check.setChecked(False)

    def _delete_selected(self) -> None:
        ids = sorted(i for i in self._selected if i in self.cards and self.cards[i].check.isEnabled())
        if not ids:
            return
        how_many = "1 reunión" if len(ids) == 1 else f"{len(ids)} reuniones"
        if not confirm(self, "Borrar reuniones",
                       f"¿Borrar {how_many} con su transcripción, su resumen y tus notas? "
                       "Esta acción no se puede deshacer.", f"Borrar {how_many}"):
            return
        self.ctl.delete_meetings(ids)
        self._set_selecting(False)
        self.refresh()
        self.ctl.window.home.refresh()  # los números de arriba del panel cambian

    # --- lista ---------------------------------------------------------------
    def refresh(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            old = item.widget()
            if old is not None:
                old.setParent(None)  # sin esto se sigue viendo hasta que Qt lo borra
                old.deleteLater()
        self.cards.clear()
        query = self.search.text().strip()
        meetings = self.ctl.meetings.list(query)
        if not meetings:
            self.list_layout.addWidget(empty_state(
                T.Glyph.SEARCH if query else T.Glyph.MEETING,
                "No hay resultados para tu búsqueda." if query else
                "Aquí aparecerán tus reuniones. Actívalas en Ajustes › Reuniones."))
        for meeting in meetings:
            card_widget = MeetingCard(meeting, self.ctl)
            card_widget.set_compact(bool(self._compact))
            card_widget.set_selecting(self._selecting)
            card_widget.check.toggled.connect(
                lambda on, meeting_id=meeting.id: self._on_check(meeting_id, on))
            self.cards[meeting.id] = card_widget
            self.list_layout.addWidget(card_widget)
        self.list_layout.addStretch(1)
        self.select_btn.setEnabled(bool(meetings))
        if self._selecting and not meetings:
            self._set_selecting(False)
        elif self._selecting:
            # Tras buscar o borrar, la selección se queda solo con lo que sigue en la lista.
            self._selected &= set(self.cards)
            for meeting_id in self._selected:
                self.cards[meeting_id].check.setChecked(True)
            self._update_selection()


# --- Modelos ------------------------------------------------------------------
class ModelRow(QWidget):
    def __init__(self, key: str, ctl: "Controller", summary: bool = False):
        super().__init__()
        self.key, self.ctl, self.summary = key, ctl, summary
        name, _, desc = (SUMMARY_MODELS if summary else MODELS)[key].partition(" · ")
        self.name = name
        v = QVBoxLayout(self)
        v.setContentsMargins(0, GAP_M, 0, GAP_M)
        v.setSpacing(GAP_S)

        top = QHBoxLayout()
        top.setSpacing(GAP_S)
        texts = QVBoxLayout()
        texts.setSpacing(GAP_XS)
        title_row = QHBoxLayout()
        title_row.setSpacing(GAP_S)
        title = label(name, "title")
        self.badge = label("EN USO", "badge")
        title_row.addWidget(title)
        title_row.addWidget(self.badge)
        title_row.addStretch(1)
        texts.addLayout(title_row)
        texts.addWidget(label(f"{MODEL_SIZES.get(key, '')} · {desc}", "dim"))
        top.addLayout(texts, 1)

        self.btn_use = icon_button(T.Glyph.CHECK, "Usar")
        self.btn_download = icon_button(T.Glyph.DOWNLOAD, "Descargar", variant="primary")
        self.btn_pause = icon_button(T.Glyph.PAUSE, "Pausar")
        self.btn_resume = icon_button(T.Glyph.PLAY, "Continuar", variant="primary")
        self.btn_retry = icon_button(T.Glyph.RETRY, "Reintentar", variant="primary")
        self.btn_cancel = icon_button(T.Glyph.CANCEL, variant="ghost", tooltip="Cancelar y borrar lo descargado")
        self.btn_delete = icon_button(T.Glyph.DELETE, variant="ghost", tooltip="Eliminar del disco")
        self.btn_use.clicked.connect(lambda: ctl.use_model(key))
        self.btn_download.clicked.connect(lambda: ctl.start_download(key))
        self.btn_pause.clicked.connect(lambda: ctl.pause_download(key))
        self.btn_resume.clicked.connect(lambda: ctl.resume_download(key))
        self.btn_retry.clicked.connect(lambda: ctl.resume_download(key))
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_delete.clicked.connect(self._delete)
        for b in (self.btn_use, self.btn_download, self.btn_pause, self.btn_resume, self.btn_retry,
                  self.btn_cancel, self.btn_delete):
            top.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        v.addLayout(top)

        self.bar = NeonProgress(8)
        self.detail = label("", "muted")
        v.addWidget(self.bar)
        v.addWidget(self.detail)
        self.refresh()

    def refresh(self) -> None:
        info = self.ctl.downloads.info(self.key)
        state = info.state
        chosen = self.ctl.settings.meeting_summary_model if self.summary else self.ctl.settings.model
        in_use = state == "installed" and chosen == self.key
        self.badge.setVisible(in_use)
        visible = {
            self.btn_use: state == "installed" and not in_use and not self.summary,
            self.btn_delete: state == "installed" and not in_use,
            self.btn_download: state == "missing",
            self.btn_pause: state in ("connecting", "downloading"),
            self.btn_resume: state == "paused",
            self.btn_retry: state == "error",
            self.btn_cancel: state in ("connecting", "downloading", "paused", "error"),
        }
        for button, on in visible.items():
            button.setVisible(on)
        in_progress = state in ("connecting", "downloading", "paused", "verifying", "error")
        self.bar.setVisible(in_progress)
        self.detail.setVisible(in_progress)
        if not in_progress:
            return
        text, mode = download_text(info)
        if self.ctl.settings.pending_model == self.key:
            text += " · se usará al terminar"
        self.bar.set_progress(info.fraction, mode)
        self.detail.setText(text)
        set_tone(self.detail, "danger" if state == "error" else ("accent" if state == "downloading" else "muted"))

    def _cancel(self) -> None:
        if confirm(self, "Cancelar descarga",
                   f"¿Cancelar la descarga de {self.name} y borrar lo que ya se descargó?", "Cancelar descarga"):
            self.ctl.cancel_download(self.key)

    def _delete(self) -> None:
        if confirm(self, "Eliminar modelo",
                   f"¿Eliminar {self.name} de tu disco ({MODEL_SIZES.get(self.key, '')})? Podrás descargarlo de nuevo.",
                   "Eliminar"):
            self.ctl.delete_model(self.key)


# --- Ajustes ------------------------------------------------------------------
class SettingsPage(QWidget):
    def __init__(self, ctl: "Controller"):
        super().__init__()
        self.ctl = ctl
        s = ctl.settings
        self._rows: list[tuple[QBoxLayout, QWidget]] = []
        self._compact: bool | None = None
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setContentsMargins(T.PAGE_MARGIN, T.PAGE_TOP, T.PAGE_MARGIN - SCROLL_GUTTER,
                                T.PAGE_BOTTOM + SHADOW_ROOM)
        root.setSpacing(T.SECTION_GAP)
        root.addLayout(page_header("CONFIGURACIÓN", "Ajustes", "Los cambios se guardan al instante."))

        # Atajo
        sec = self._section(root, T.Glyph.KEYBOARD, "Atajo de teclado")
        hot = QWidget()
        hl = QHBoxLayout(hot)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(GAP_M)
        self.keycaps = KeyCaps(s.hotkey)
        self.capture_btn = icon_button(T.Glyph.KEYBOARD, "Cambiar atajo")
        self.capture_btn.clicked.connect(self._toggle_capture)
        hl.addWidget(self.keycaps)
        hl.addWidget(self.capture_btn)
        self._row(sec, "Combinación", "Funciona en cualquier app, aunque NeonWhisper esté minimizado.", hot)
        self.capture_msg = paragraph()
        self.capture_msg.hide()
        sec.addWidget(self.capture_msg)
        self.mode_toggle = self._segmented(
            [("toggle", "Iniciar / detener"), ("hold", "Mantener presionado")], s.mode,
            lambda v: ctl.update_setting("mode", v),
        )
        self._row(sec, "Modo", "Presiona una vez para empezar y otra para pegar, o mantén las teclas mientras hablas.",
                  self.mode_toggle, last=True)

        # Whisper
        sec = self._section(root, T.Glyph.BOLT, "Whisper")
        self._row(sec, "Procesador", "Con tu GPU NVIDIA la transcripción tarda una fracción de segundo.",
                  self._combo({"auto": "Automático (GPU si hay)", "cuda": "GPU NVIDIA (CUDA)", "cpu": "CPU"},
                              s.device, lambda v: ctl.update_setting("device", v)))
        self._row(sec, "Idioma", "Fijar el idioma es más rápido y preciso que detectarlo.",
                  self._combo(LANGUAGES, s.language, lambda v: ctl.update_setting("language", v)))
        self.prompt = QLineEdit(s.initial_prompt)
        self.prompt.setPlaceholderText("Luisart, LART, Talanty, CFA…")
        readable_hint(self.prompt)
        self.prompt.setMinimumWidth(300)
        self.prompt.editingFinished.connect(lambda: ctl.update_setting("initial_prompt", self.prompt.text()))
        self._row(sec, "Vocabulario", "Nombres y términos que Whisper debe escribir bien.", self.prompt, last=True)

        # Modelos
        sec = self._section(root, T.Glyph.DOWNLOAD, "Modelos de Whisper")
        sec.addWidget(paragraph(
            "Large v3 Turbo es casi tan preciso como Large v3 y varias veces más rápido. "
            "Puedes pausar una descarga y continuarla después, incluso si cierras la app."))
        self.model_rows: dict[str, ModelRow] = {}
        for i, key in enumerate(MODELS):
            if i:
                sec.addWidget(separator())
            self.model_rows[key] = ModelRow(key, ctl)
            sec.addWidget(self.model_rows[key])

        # Audio
        sec = self._section(root, T.Glyph.MIC, "Audio")
        self.mic_combo = NoWheelComboBox()
        self.mic_combo.addItem("Predeterminado de Windows", "")
        for _, name in list_input_devices():
            if self.mic_combo.findData(name) < 0:
                self.mic_combo.addItem(name, name)
        current_mic = s.input_device_name or device_name(s.input_device)
        if current_mic and self.mic_combo.findData(current_mic) < 0:
            self.mic_combo.addItem(f"{current_mic} (desconectado)", current_mic)
        self.mic_combo.setCurrentIndex(max(0, self.mic_combo.findData(current_mic)))
        self.mic_combo.currentIndexChanged.connect(self._on_mic_selected)
        mic_host = QWidget()
        mh = QHBoxLayout(mic_host)
        mh.setContentsMargins(0, 0, 0, 0)
        mh.setSpacing(GAP_M)
        mh.addWidget(self.mic_combo)
        self.mic_test_btn = icon_button(T.Glyph.MIC, "Probar")
        self.mic_test_btn.clicked.connect(self._toggle_mic_test)
        mh.addWidget(self.mic_test_btn)
        self._row(sec, "Micrófono", "Pruébalo: graba 4 segundos, mide el nivel y te reproduce lo que grabó.",
                  mic_host, last=True)
        self.mic_tester = MicTester()
        self.mic_tester.changed.connect(self._on_mic_test)
        self.mic_panel = QWidget()
        mp = QHBoxLayout(self.mic_panel)
        mp.setContentsMargins(0, 0, 0, GAP_M)
        mp.setSpacing(GAP_L)
        self.mic_bars = WaveBars(lambda: self.mic_tester.level, height=WAVE_H)
        self.mic_status = label("", "muted", wrap=True)
        self.mic_status.setMinimumWidth(280)
        mp.addWidget(self.mic_bars, 1)
        mp.addWidget(self.mic_status, 1)
        self.mic_panel.hide()
        sec.addWidget(self.mic_panel)
        sec.addWidget(separator())
        self._row(sec, "Sonidos", "Un chime corto al empezar y terminar de grabar.",
                  self._toggle(s.sounds, lambda v: ctl.update_setting("sounds", v)))
        vol = QWidget()
        vl = QHBoxLayout(vol)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(GAP_M)
        slider = NoWheelSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(int(s.sound_volume * 100))
        slider.setFixedWidth(SLIDER_W)
        slider.sliderReleased.connect(lambda: ctl.update_setting("sound_volume", slider.value() / 100))
        test = icon_button(T.Glyph.PLAY, "Probar")
        test.clicked.connect(ctl.test_sound)
        vl.addWidget(slider)
        vl.addWidget(test)
        self._row(sec, "Volumen de sonidos", "", vol, last=True)

        # Reuniones
        sec = self._section(root, T.Glyph.HISTORY, "Reuniones")
        sec.addWidget(paragraph(
            "NeonWhisper mira si una app de reuniones (Teams, Zoom, Meet, Webex, Discord…) está usando tu "
            "micrófono. Cuando eso pasa, graba tu voz y lo que suena en tu PC, y al terminar transcribe y "
            "resume, todo en tu computadora. Avisa a los demás de que estás grabando: en muchos sitios es "
            "obligatorio."))
        sec.addSpacing(GAP_S)
        self._row(sec, "Grabar reuniones", "Con esto apagado, NeonWhisper no vigila nada ni graba.",
                  self._toggle(s.meetings_enabled, lambda v: ctl.update_setting("meetings_enabled", v)))
        self._row(sec, "Empezar sin preguntar", "Si lo apagas, solo te avisa y tú le das a Grabar.",
                  self._toggle(s.meeting_auto_start, lambda v: ctl.update_setting("meeting_auto_start", v)))
        self._row(sec, "Grabar tu micrófono",
                  "Tu voz en la grabación. Puedes silenciarla en caliente desde la pestaña Reuniones.",
                  self._toggle(s.meeting_record_mic, lambda v: ctl.update_setting("meeting_record_mic", v)))
        self._row(sec, "Grabar el audio del sistema",
                  "Lo que dicen los demás, además de tu micrófono. Se captura de tu salida de audio "
                  "(bocinas o audífonos) sin instalar nada.",
                  self._toggle(s.meeting_capture_system, lambda v: ctl.update_setting("meeting_capture_system", v)))
        self.speaker_combo = NoWheelComboBox()
        self._fill_speakers(s.meeting_speaker)
        self.speaker_combo.currentIndexChanged.connect(
            lambda _: ctl.update_setting("meeting_speaker", self.speaker_combo.currentData() or ""))
        self._row(sec, "Salida que se captura",
                  "De dónde se toma el audio de los demás. Debe ser por donde los escuchas.",
                  self.speaker_combo)
        self._row(sec, "Aviso flotante",
                  "Un recuadro pequeño arriba a la izquierda al detectar la reunión, con el botón de grabar.",
                  self._toggle(s.meeting_popup, lambda v: ctl.update_setting("meeting_popup", v)))
        self._row(sec, "Conservar el audio", "Guarda el .wav de la reunión. Ocupa ~2 MB por minuto.",
                  self._toggle(s.meeting_keep_audio, lambda v: ctl.update_setting("meeting_keep_audio", v)))
        # Probar las dos fuentes antes de una reunión de verdad.
        self.meeting_audio = MeetingAudioTester()
        self.meeting_audio.changed.connect(self._on_meeting_audio_test)
        audio_host = QWidget()
        ah = QHBoxLayout(audio_host)
        ah.setContentsMargins(0, 0, 0, 0)
        ah.setSpacing(GAP_M)
        self.meeting_bars = WaveBars(lambda: self.meeting_audio.level, height=WAVE_H)
        self.meeting_bars.setFixedWidth(160)
        self.meeting_test_btn = icon_button(T.Glyph.PLAY, "Probar")
        self.meeting_test_btn.clicked.connect(self._toggle_meeting_audio_test)
        ah.addWidget(self.meeting_bars)
        ah.addWidget(self.meeting_test_btn)
        self._row(sec, "Probar qué se grabaría",
                  "Cinco segundos escuchando las dos fuentes: habla y deja sonando un video.", audio_host)
        self.meeting_audio_status = paragraph()
        self.meeting_audio_status.hide()
        sec.addWidget(self.meeting_audio_status)
        sec.addWidget(separator())
        self._row(sec, "Duración mínima",
                  "Las reuniones más cortas que esto se descartan (útil bajarlo para probar).",
                  self._combo({"15": "15 segundos", "30": "30 segundos", "60": "1 minuto", "180": "3 minutos"},
                              str(s.meeting_min_seconds),
                              lambda v: ctl.update_setting("meeting_min_seconds", int(v))))
        self._row(sec, "Transcripción en vivo",
                  "Ir transcribiendo mientras la reunión ocurre, en la pestaña Reuniones.",
                  self._toggle(s.meeting_live_transcript,
                               lambda v: ctl.update_setting("meeting_live_transcript", v)))
        self._row(sec, "Plantilla del resumen", "El formato del resumen según el tipo de reunión.",
                  self._combo({k: f"{name} · {desc}" for k, (name, desc, _) in TEMPLATES.items()},
                              s.meeting_template, lambda v: ctl.update_setting("meeting_template", v)))
        self._row(sec, "Resumen automático", "El modelo que escribe el resumen al terminar la reunión.",
                  self._combo({**{"": "Solo transcripción, sin resumen"}, **SUMMARY_MODELS},
                              s.meeting_summary_model,
                              lambda v: ctl.update_setting("meeting_summary_model", v)))
        self.summary_rows: dict[str, ModelRow] = {}
        for key in SUMMARY_MODELS:
            sec.addWidget(separator())
            self.summary_rows[key] = ModelRow(key, ctl, summary=True)
            sec.addWidget(self.summary_rows[key])

        # Apariencia
        sec = self._section(root, T.Glyph.THEME, "Apariencia")
        sec.addWidget(paragraph("El tema pinta toda la app: fondos, acentos, el orbe del micrófono y el "
                                "ícono. El cambio es inmediato, no hace falta reiniciar."))
        sec.addSpacing(GAP_S)
        theme_host = QWidget()
        # 250 y no menos: por debajo caben cuatro por fila y la descripción de la tarjeta se
        # corta a media palabra. Curiosamente solo pasaba con la ventana grande.
        theme_cards = CardFlow(250, T.CARD_GAP, theme_host)
        self.theme_group = QButtonGroup(self)
        self.theme_cards: dict[str, ThemeCard] = {}
        for key in T.THEMES:
            c = ThemeCard(key)
            c.setChecked(key == s.ui_theme)
            c.clicked.connect(lambda _=False, k=key: ctl.update_setting("ui_theme", k))
            self.theme_group.addButton(c)
            self.theme_cards[key] = c
            theme_cards.addWidget(c)
        sec.addWidget(theme_host)
        sec.addSpacing(GAP_L)
        sec.addWidget(separator())
        self._row(sec, "Barra flotante a juego",
                  "Al cambiar de tema, la barra flotante se pone el diseño del mismo nombre. "
                  "Apágalo para combinarlos a tu gusto.",
                  self._toggle(s.theme_syncs_overlay, lambda v: ctl.update_setting("theme_syncs_overlay", v)),
                  last=True)

        # Barra flotante
        sec = self._section(root, T.Glyph.PALETTE, "Barra flotante")
        self._row(sec, "Mostrar barra flotante", "La barra de voz que aparece sobre tus apps mientras dictas.",
                  self._toggle(s.show_overlay, lambda v: ctl.update_setting("show_overlay", v)))
        design = QWidget()
        dv = QVBoxLayout(design)
        dv.setContentsMargins(0, GAP_M, 0, GAP_M)
        dv.setSpacing(GAP_XS)
        dv.addWidget(label("Diseño", "title"))
        dv.addWidget(paragraph("Al cambiar cualquier opción, la barra aparece unos segundos para que veas "
                               "cómo queda."))
        dv.addSpacing(GAP_S)
        cards_host = QWidget()
        cards = CardFlow(250, T.CARD_GAP, cards_host)
        self.style_group = QButtonGroup(self)
        self.style_cards: dict[str, OverlayStyleCard] = {}
        for key in STYLES:
            c = OverlayStyleCard(key, s)
            c.setChecked(key == s.overlay_style)
            c.clicked.connect(lambda _=False, k=key: self._set_overlay("overlay_style", k))
            self.style_group.addButton(c)
            self.style_cards[key] = c
            cards.addWidget(c)
        dv.addWidget(cards_host)
        sec.addWidget(design)
        sec.addWidget(separator())
        self.overlay_sliders = {
            "overlay_scale": self._percent_slider(s.overlay_scale, 70, 150, "overlay_scale"),
            "overlay_bg_opacity": self._percent_slider(s.overlay_bg_opacity, 0, 100, "overlay_bg_opacity"),
            "overlay_opacity": self._percent_slider(s.overlay_opacity, 30, 100, "overlay_opacity"),
        }
        self._row(sec, "Tamaño", "Qué tan grande se ve la barra en tu pantalla.",
                  self.overlay_sliders["overlay_scale"])
        self._row(sec, "Fondo", "Bájalo para ver lo que hay detrás; las ondas y el texto siguen visibles.",
                  self.overlay_sliders["overlay_bg_opacity"])
        self._row(sec, "Opacidad", "Transparencia de toda la barra: fondo, ondas y texto.",
                  self.overlay_sliders["overlay_opacity"])
        actions = QWidget()
        al = QHBoxLayout(actions)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(GAP_M)
        preview = icon_button(T.Glyph.PLAY, "Vista previa")
        preview.clicked.connect(ctl.preview_overlay)
        reset = icon_button(T.Glyph.RETRY, "Restablecer", "ghost", "Volver al diseño Neón original")
        reset.clicked.connect(self._reset_overlay)
        al.addWidget(reset)
        al.addWidget(preview)
        self._row(sec, "Probar", "Muestra la barra con voz simulada durante 3 segundos.", actions, last=True)

        # Comportamiento
        sec = self._section(root, T.Glyph.PASTE, "Comportamiento")
        self._row(sec, "Pegar automáticamente", "Si lo apagas, el texto solo se copia al portapapeles.",
                  self._toggle(s.auto_paste, lambda v: ctl.update_setting("auto_paste", v)))
        self._row(sec, "Restaurar portapapeles", "Después de pegar, vuelve a dejar lo que tenías copiado.",
                  self._toggle(s.restore_clipboard, lambda v: ctl.update_setting("restore_clipboard", v)))
        self._row(sec, "Iniciar con Windows", "Arranca NeonWhisper en la bandeja al encender tu PC.",
                  self._toggle(s.launch_at_startup, lambda v: ctl.update_setting("launch_at_startup", v)))
        self._row(sec, "Iniciar minimizado", "Abre directo en la bandeja del sistema.",
                  self._toggle(s.start_minimized, lambda v: ctl.update_setting("start_minimized", v)), last=True)

        # Datos
        sec = self._section(root, T.Glyph.FOLDER, "Datos")
        folders = QWidget()
        fl = QHBoxLayout(folders)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(GAP_M)
        open_data = icon_button(T.Glyph.FOLDER, "Historial y ajustes")
        open_data.clicked.connect(lambda: os.startfile(DATA_DIR))
        open_models = icon_button(T.Glyph.FOLDER, "Modelos")
        open_models.clicked.connect(lambda: os.startfile(MODELS_DIR))
        fl.addWidget(open_data)
        fl.addWidget(open_models)
        self._row(sec, "Carpetas", "Todo se guarda en tu PC: nada sale de aquí.", folders, last=True)

        # Actualizaciones
        sec = self._section(root, T.Glyph.GLOBE, "Actualizaciones")
        sec.addWidget(paragraph(
            "NeonWhisper mira la rama «main» del repositorio público y compara el número de "
            "versión con el tuyo. Si lo que tienes es más nuevo que lo publicado, te dirá que "
            "estás al día: es lo correcto, aunque de momento pueda sonar raro."))
        sec.addSpacing(GAP_S)
        self.updater = Updater(self)
        self.updater.checked.connect(self._on_update_checked)
        self.updater.check_failed.connect(self._on_update_failed)
        self.updater.launching.connect(self._on_update_launching)
        self.updater.launch_failed.connect(self._on_update_launch_failed)
        self.check_btn = icon_button(T.Glyph.RETRY, "Buscar actualizaciones")
        self.check_btn.clicked.connect(self._check_updates)
        self._row(sec, "Versión instalada", f"Tienes la v{__version__}.", self.check_btn, last=True)

        update_panel = QWidget()
        uv = QVBoxLayout(update_panel)
        uv.setContentsMargins(0, 0, 0, GAP_M)
        uv.setSpacing(GAP_M)
        self.update_status = paragraph()
        uv.addWidget(self.update_status)
        self.update_actions = QWidget()
        ua = QHBoxLayout(self.update_actions)
        ua.setContentsMargins(0, 0, 0, 0)
        ua.setSpacing(GAP_M)
        # Una copia que no se puede actualizar así (un clon de git, por ejemplo) lo dice desde ya.
        # El botón se queda, pero sin el relleno primario: apagado, ese relleno lo tapaba y parecía
        # que sí se podía picar.
        self._can_update, self._update_reason = can_update()
        self.install_btn = icon_button(T.Glyph.DOWNLOAD, "Actualizar ahora",
                                       variant="primary" if self._can_update else None)
        self.install_btn.setEnabled(self._can_update)
        if not self._can_update:
            self.install_btn.setToolTip(self._update_reason)
        self.install_btn.clicked.connect(self._install_update)
        changes_btn = icon_button(T.Glyph.GLOBE, "Ver qué cambió", variant="ghost", tooltip=RELEASES_URL)
        changes_btn.clicked.connect(lambda: webbrowser.open(RELEASES_URL))
        ua.addWidget(self.install_btn)
        ua.addWidget(changes_btn)
        ua.addStretch(1)
        self.update_actions.hide()
        uv.addWidget(self.update_actions)
        sec.addWidget(update_panel)
        if not self._can_update:
            self._set_update_status(self._update_reason, "muted")

        root.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrollable(inner))

    # --- helpers -------------------------------------------------------------
    @staticmethod
    def _section(root: QVBoxLayout, glyph: str, title: str) -> QVBoxLayout:
        frame = card()
        v = QVBoxLayout(frame)
        v.setContentsMargins(T.CARD_PAD, T.CARD_PAD, T.CARD_PAD, GAP_M)
        v.setSpacing(0)
        head = QHBoxLayout()
        head.setSpacing(GAP_M)
        head.addWidget(GlyphLabel(glyph, "CYAN", 18))
        head.addWidget(label(title, "h2"))
        head.addStretch(1)
        v.addLayout(head)
        v.addSpacing(GAP_S)
        root.addWidget(frame)
        return v

    def _row(self, section: QVBoxLayout, title: str, desc: str, control: QWidget, last: bool = False) -> None:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, GAP_M, 0, GAP_M)
        h.setSpacing(GAP_XL)
        text_host = QWidget()
        text_host.setMaximumWidth(520)  # a 1920 px el rótulo quedaba a un metro de su control
        text = QVBoxLayout(text_host)
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(GAP_XS)
        text.addWidget(label(title, "title"))
        if desc:
            text.addWidget(label(desc, "muted", wrap=True))
        h.addWidget(text_host, 1)
        h.addStretch(0)
        h.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        section.addWidget(row)
        self._rows.append((h, control))
        if not last:
            section.addWidget(separator())

    # --- ventana angosta -----------------------------------------------------
    def set_compact(self, compact: bool) -> None:
        """Con poco ancho el control baja debajo de su rótulo en vez de estrujarlo en una columna."""
        if compact == self._compact:
            return
        self._compact = compact
        for h, control in self._rows:
            h.setDirection(QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight)
            h.setSpacing(GAP_S if compact else GAP_XL)
            h.setAlignment(control, (Qt.AlignmentFlag.AlignLeft if compact else Qt.AlignmentFlag.AlignRight)
                           | Qt.AlignmentFlag.AlignVCenter)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.set_compact(self.width() < COMPACT_WIDTH)

    # --- barra flotante -------------------------------------------------------
    def _percent_slider(self, value: float, lo: int, hi: int, key: str) -> QWidget:
        host = QWidget()
        h = QHBoxLayout(host)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(GAP_M)
        slider = NoWheelSlider(Qt.Orientation.Horizontal)
        slider.setRange(lo, hi)
        slider.setPageStep(10)
        slider.setFixedWidth(SLIDER_W)
        pct = label("", "pct")
        pct.setFixedWidth(48)
        pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        def changed(v: int) -> None:
            pct.setText(f"{v}%")
            self._set_overlay(key, v / 100)

        slider.setValue(round(value * 100))
        pct.setText(f"{slider.value()}%")
        slider.valueChanged.connect(changed)
        h.addWidget(slider)
        h.addWidget(pct)
        host.slider = slider
        return host

    def _set_overlay(self, key: str, value) -> None:
        if getattr(self.ctl.settings, key) == value:
            self.ctl.preview_overlay()
        else:
            self.ctl.update_setting(key, value)
        for c in self.style_cards.values():
            c.update()

    def _reset_overlay(self) -> None:
        self.ctl.reset_overlay_look()
        s = self.ctl.settings
        for key, host in self.overlay_sliders.items():
            host.slider.setValue(round(getattr(s, key) * 100))
        self.style_cards[s.overlay_style].setChecked(True)
        for c in self.style_cards.values():
            c.update()

    def set_theme_selection(self, key: str) -> None:
        """Marca el tema activo y vuelve a dibujar las miniaturas."""
        if key in self.theme_cards:
            self.theme_cards[key].setChecked(True)
        for c in (*self.theme_cards.values(), *self.style_cards.values()):
            c.update()
        style_card = self.style_cards.get(self.ctl.settings.overlay_style)
        if style_card:
            style_card.setChecked(True)

    def _fill_speakers(self, current: str) -> None:
        from neonwhisper.meetings import list_speakers

        self.speaker_combo.blockSignals(True)
        self.speaker_combo.clear()
        self.speaker_combo.addItem("Salida predeterminada de Windows", "")
        for name in list_speakers():
            self.speaker_combo.addItem(name, name)
        if current and self.speaker_combo.findData(current) < 0:
            self.speaker_combo.addItem(f"{current} (no conectada)", current)
        self.speaker_combo.setCurrentIndex(max(0, self.speaker_combo.findData(current)))
        self.speaker_combo.blockSignals(False)

    def refresh_models(self, key: str | None = None) -> None:
        for k, row in {**self.model_rows, **self.summary_rows}.items():
            if key is None or k == key:
                row.refresh()

    def _on_mic_selected(self, _index: int) -> None:
        self.stop_mic_test()
        self.ctl.update_setting("input_device", None)
        self.ctl.update_setting("input_device_name", self.mic_combo.currentData() or "")

    # --- prueba de micrófono -------------------------------------------------
    def _toggle_mic_test(self) -> None:
        if self.mic_tester.active:
            self.mic_tester.stop()
            return
        if self.ctl.recorder.recording:
            return
        self.mic_panel.show()
        s = self.ctl.settings
        self.mic_tester.start(resolve_input_device(s.input_device_name, s.input_device))

    def stop_mic_test(self) -> None:
        if self.mic_tester.active:
            self.mic_tester.stop()
        if self.meeting_audio.active:
            self.meeting_audio.stop()

    # --- prueba del audio de reuniones ---------------------------------------
    def _toggle_meeting_audio_test(self) -> None:
        if self.meeting_audio.active:
            self.meeting_audio.stop()
            return
        if self.ctl.recorder.recording or self.ctl.meeting_recorder.recording:
            return
        self.mic_tester.stop()
        s = self.ctl.settings
        self.meeting_audio.start(resolve_input_device(s.input_device_name, s.input_device), s.meeting_speaker)

    def _on_meeting_audio_test(self, state: str, message: str) -> None:
        active = state == "testing"
        self.meeting_bars.set_mode("recording" if active else "idle")
        self.meeting_test_btn.setText("Detener" if active else "Probar")
        set_tone(self.meeting_audio_status,
                 {"ok": "ok", "warn": "danger", "error": "danger"}.get(state, "accent"))
        self.meeting_audio_status.setText(message)
        self.meeting_audio_status.setVisible(bool(message))

    def _on_mic_test(self, state: str, message: str) -> None:
        active = state in ("recording", "playing")
        self.mic_bars.set_mode("recording" if active else "idle")
        self.mic_test_btn.setText("Detener" if active else "Probar otra vez")
        tone = {"ok": "ok", "silent": "danger", "error": "danger"}.get(state, "accent" if active else "muted")
        set_tone(self.mic_status, tone)
        self.mic_status.setText(message)

    @staticmethod
    def _combo(options: dict[str, str], current: str, on_change) -> QComboBox:
        combo = NoWheelComboBox()
        for key, text in options.items():
            combo.addItem(text, key)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        combo.currentIndexChanged.connect(lambda _: on_change(combo.currentData()))
        return combo

    @staticmethod
    def _toggle(value: bool, on_change) -> ToggleSwitch:
        sw = ToggleSwitch(value)
        sw.toggled.connect(on_change)
        return sw

    @staticmethod
    def _segmented(options: list[tuple[str, str]], current: str, on_change) -> QWidget:
        host = QWidget()
        h = QHBoxLayout(host)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        group = QButtonGroup(host)
        for i, (key, text) in enumerate(options):
            b = QPushButton(text)
            b.setObjectName("Segment")
            b.setCheckable(True)
            b.setChecked(key == current)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setProperty("pos", "first" if i == 0 else "last" if i == len(options) - 1 else "mid")
            b.clicked.connect(lambda _=False, k=key: on_change(k))
            group.addButton(b)
            h.addWidget(b)
        host._group = group  # mantener referencia viva
        return host

    # --- actualizar la app ---------------------------------------------------
    def _set_update_status(self, text: str, tone: str) -> None:
        set_tone(self.update_status, tone)
        self.update_status.setText(text)

    def _check_updates(self) -> None:
        if self.updater.busy:
            return
        self.check_btn.setEnabled(False)
        self.update_actions.hide()
        self._set_update_status("Preguntando a GitHub qué versión hay publicada…", "accent")
        self.updater.check()

    def _on_update_checked(self, version: str, newer: bool) -> None:
        self.check_btn.setEnabled(True)
        if newer:
            news = f"Hay una versión nueva: v{version}. Tú tienes la v{__version__}."
            # Si esta copia no se puede actualizar sola, el motivo va aquí: si no, el aviso de
            # «hay versión nueva» pisaba la explicación y el botón apagado quedaba sin justificar.
            self._set_update_status(news if self._can_update else f"{news} {self._update_reason}",
                                    "accent" if self._can_update else "muted")
            self.update_actions.show()
        else:
            self._set_update_status(
                f"Estás al día: lo publicado es la v{version} y tú tienes la v{__version__}.", "ok")
            self.update_actions.hide()

    def _on_update_failed(self, reason: str) -> None:
        self.check_btn.setEnabled(True)
        self.update_actions.hide()
        # No es un fallo de la app: casi siempre es que no hay internet. Se dice sin alarmar.
        self._set_update_status(f"No pude preguntarle a GitHub: {reason}. Inténtalo más tarde.", "muted")

    def _install_update(self) -> None:
        version = self.updater.latest or "más reciente"
        if not confirm(self, "Actualizar NeonWhisper",
                       f"Voy a instalar la v{version}.\n\n"
                       "NeonWhisper se cerrará para reemplazar sus archivos y se volverá a abrir "
                       "solo al terminar. Verás una ventana con el progreso. Tus dictados, tus "
                       "reuniones y tus ajustes no se tocan.",
                       "Actualizar y reiniciar"):
            return
        self.updater.install()

    def _on_update_launching(self) -> None:
        self.install_btn.setEnabled(False)
        self.check_btn.setEnabled(False)
        self._set_update_status("Actualizando… NeonWhisper se va a cerrar y volverá solo.", "accent")

    def _on_update_launch_failed(self, reason: str) -> None:
        self.install_btn.setEnabled(False)
        self._set_update_status(f"No se pudo lanzar el actualizador: {reason}", "danger")

    # --- captura del atajo -------------------------------------------------
    def _toggle_capture(self) -> None:
        if self.ctl.capturing_hotkey:
            self.ctl.cancel_hotkey_capture()
        else:
            self.ctl.begin_hotkey_capture()

    def set_capturing(self, active: bool) -> None:
        self.capture_btn.setText("Presiona la combinación…  (Esc cancela)" if active else "Cambiar atajo")
        self.capture_btn.setProperty("variant", "primary" if active else None)
        self.capture_btn.style().unpolish(self.capture_btn)
        self.capture_btn.style().polish(self.capture_btn)
        if active:
            self.capture_msg.hide()

    def show_capture_message(self, text: str) -> None:
        self.capture_msg.setText(text)
        self.capture_msg.setVisible(bool(text))

    def set_hotkey(self, hotkey: str) -> None:
        self.keycaps.set_hotkey(hotkey)


# --- Ventana ------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, ctl: "Controller"):
        super().__init__()
        self.ctl = ctl
        self.setWindowTitle("NeonWhisper")
        self.setWindowIcon(make_app_icon())
        # En 1366x768 o al 150 % de escalado, 1140x760 no cabía: la ventana se ajusta a la pantalla.
        avail = self.screen().availableGeometry()
        self.resize(min(1140, avail.width() - 80), min(760, avail.height() - 60))
        self.setMinimumSize(900, 620)
        self._titlebar_done = False

        root = QWidget()
        root.setObjectName("Root")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(224)
        sv = QVBoxLayout(sidebar)
        sv.setContentsMargins(GAP_M, GAP_XL, GAP_M, GAP_L)
        sv.setSpacing(GAP_S)
        brand = QHBoxLayout()
        brand.setSpacing(GAP_M)
        self.logo = Logo(40)
        brand.addWidget(self.logo)
        name = QLabel()
        on_restyle(name, lambda: name.setText(
            f"<span style='color:{T.ICE}'>NEON</span><span style='color:{T.TEXT}'>WHISPER</span>"))
        name.setObjectName("Brand")  # el tamaño va en la hoja de estilos: si no, la pisa
        add_glow(name, blur=24, alpha=0.5)
        brand.addWidget(name)
        brand.addStretch(1)
        sv.addLayout(brand)
        sv.addSpacing(GAP_XL)

        self.stack = QStackedWidget()
        self.home = HomePage(ctl)
        self.history = HistoryPage(ctl)
        self.meetings = MeetingsPage(ctl)
        self.settings = SettingsPage(ctl)
        nav_group = QButtonGroup(self)
        for i, (glyph, text, page) in enumerate((
            (T.Glyph.HOME, "Inicio", self.home),
            (T.Glyph.HISTORY, "Historial", self.history),
            (T.Glyph.MEETING, "Reuniones", self.meetings),
            (T.Glyph.SETTINGS, "Ajustes", self.settings),
        )):
            self.stack.addWidget(page)
            btn = QPushButton(f"   {text}")
            btn.setObjectName("NavButton")
            set_glyph_icon(btn, lambda g=glyph: glyph_icon(g))
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, idx=i: self.stack.setCurrentIndex(idx))
            nav_group.addButton(btn)
            sv.addWidget(btn)
        self.nav_buttons = nav_group.buttons()
        # Al volver a Inicio, el panel vuelve a leer reuniones, notas y dictados.
        self.stack.currentChanged.connect(
            lambda index: self.home.refresh() if index == 0 else None)
        sv.addStretch(1)

        status = card()
        st = QHBoxLayout(status)
        st.setContentsMargins(GAP_L, GAP_L, GAP_L, GAP_L)
        st.setSpacing(GAP_M)
        self.dot = StatusDot()
        st.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(GAP_XS)
        self.model_title = label("Preparando…", "title")
        self.model_detail = label("", "dim", wrap=True)
        texts.addWidget(self.model_title)
        texts.addWidget(self.model_detail)
        self.dl_label = label("", "muted", wrap=True)
        self.dl_bar = NeonProgress(6)
        texts.addSpacing(GAP_S)
        texts.addWidget(self.dl_label)
        texts.addWidget(self.dl_bar)
        self.dl_label.hide()
        self.dl_bar.hide()
        st.addLayout(texts, 1)
        sv.addWidget(status)
        sv.addWidget(label("100% local · privado", "dim"), 0, Qt.AlignmentFlag.AlignHCenter)

        h.addWidget(sidebar)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)

    def go_to(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)

    def set_model_status(self, state: str, detail: str) -> None:
        self.dot.state = state
        titles = {"downloading": "Descargando modelo", "loading": "Iniciando modelo", "ready": "Whisper listo", "error": "Error del modelo"}
        self.model_title.setText(titles.get(state, state))
        self.model_detail.setText(detail)

    def set_download_summary(self, text: str | None, fraction: float = 0.0, mode: str = "active") -> None:
        visible = bool(text)
        self.dl_label.setVisible(visible)
        self.dl_bar.setVisible(visible)
        if visible:
            set_tone(self.dl_label, "danger" if mode == "error"
                     else ("accent" if mode in ("active", "indeterminate") else "muted"))
            self.dl_label.setText(text)
            self.dl_bar.set_progress(fraction, mode)

    def set_recording_indicator(self, recording: bool) -> None:
        self.logo.active = recording
        self.logo.update()

    def restyle(self) -> None:
        """Repinta toda la ventana con el tema activo."""
        self.setWindowIcon(make_app_icon())
        restyle(self)
        self.settings.set_theme_selection(self.ctl.settings.ui_theme)
        # internalWinId() en vez de winId(): el segundo CREA el hueco nativo si no lo hay (y lo
        # vuelve a crear con otro número si Qt lo había soltado), así que pintar la barra de título
        # podía acabar fabricando una ventana de Windows a espaldas de la app. Si todavía no existe
        # no hay nada que pintar: ya lo hace showEvent cuando aparece.
        T.apply_titlebar(self.internalWinId() or 0)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._titlebar_done:
            T.apply_titlebar(int(self.winId()))
            self._titlebar_done = True

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.ctl.quitting:
            event.accept()
            return
        event.ignore()
        self.hide()
        self.ctl.on_window_hidden()
