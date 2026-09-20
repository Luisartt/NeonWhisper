"""Ventana principal: Inicio, Historial y Ajustes."""
import os
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QShowEvent
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSlider, QStackedWidget, QVBoxLayout, QWidget,
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
from neonwhisper.ui.widgets import (
    CardFlow, ClickCard, ElidedLabel, GlyphLabel, KeyCaps, Logo, MicOrb, NeonProgress, OverlayStyleCard, StatusDot,
    ThemeCard, ToggleSwitch, WaveBars, add_glow, card, glyph_icon, label, make_app_icon, on_restyle, repolish,
    restyle, set_glyph_icon, set_tone,
)
from neonwhisper.ui.overlay_styles import STYLES

if TYPE_CHECKING:
    from neonwhisper.app import Controller

MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

# Color del estado de una reunión (en el panel de inicio y en la lista de Reuniones).
STATE_TONES = {"grabando": "danger", "transcribiendo": "accent", "resumiendo": "accent", "lista": "ok",
               "error": "danger"}


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


def scrollable(inner: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(inner)
    return area


def page_header(eyebrow: str, title: str, subtitle: str = "") -> QVBoxLayout:
    box = QVBoxLayout()
    box.setSpacing(6)
    box.addWidget(label(eyebrow, "eyebrow"))
    h1 = label(title, "h1")
    box.addWidget(h1)
    if subtitle:
        box.addWidget(label(subtitle, "muted", wrap=True))
    return box


def icon_button(glyph: str, text: str = "", variant: str | None = None, tooltip: str = "") -> QPushButton:
    btn = QPushButton(text)
    set_glyph_icon(btn, lambda: glyph_icon(glyph, color=T.ON_ACCENT if variant == "primary" else T.MUTED))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if variant:
        btn.setProperty("variant", variant)
    if tooltip:
        btn.setToolTip(tooltip)
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
    v.setContentsMargins(18, 14, 18, 14)
    v.setSpacing(0)
    value = label("—", "stat")
    v.addWidget(ElidedLabel(title, "mini"))
    v.addWidget(value)
    return tile, value


def panel_row(title: str, meta: str, state: str = "", tone: str | None = None) -> QFrame:
    """Una línea dentro de una tarjeta del panel: texto, datos y, si aplica, su estado."""
    row = QFrame()
    row.setObjectName("Row")
    h = QHBoxLayout(row)
    h.setContentsMargins(12, 9, 12, 9)
    h.setSpacing(12)
    texts = QVBoxLayout()
    texts.setSpacing(2)
    head = ElidedLabel(title)
    head.setProperty("role", "strong")
    texts.addWidget(head)
    texts.addWidget(ElidedLabel(meta, "dim"))
    h.addLayout(texts, 1)
    if state:
        chip = label(state, "chip")
        set_tone(chip, tone)
        h.addWidget(chip, 0, Qt.AlignmentFlag.AlignVCenter)
    return row


class PanelCard(ClickCard):
    """Tarjeta del panel: encabezado, filas y «ver todo». El clic lleva a su pestaña."""

    def __init__(self, glyph: str, title: str, hint: str, on_open) -> None:
        super().__init__()
        self.setMinimumHeight(212)
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 18, 16, 16)
        v.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(10)
        head.setContentsMargins(6, 0, 6, 0)
        head.addWidget(GlyphLabel(glyph, "CYAN", 18))
        head.addWidget(label(title, "h2"))
        head.addStretch(1)
        head.addWidget(label(hint, "mini"))
        v.addLayout(head)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(2)
        v.addLayout(self.rows)
        v.addStretch(1)
        self.clicked.connect(on_open)

    def fill(self, rows: list[QFrame], empty: str) -> None:
        while self.rows.count():
            item = self.rows.takeAt(0)
            old = item.widget()
            if old is not None:
                old.setParent(None)  # sin esto se sigue viendo hasta que Qt lo borra
                old.deleteLater()
        if not rows:
            blank = label(empty, "muted", wrap=True)
            blank.setContentsMargins(12, 10, 12, 10)
            self.rows.addWidget(blank)
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
        root.setContentsMargins(T.PAGE_MARGIN, 30, T.PAGE_MARGIN - 8, 28)
        root.setSpacing(T.BLOCK_GAP)
        root.addLayout(page_header(
            "TODO EN TU PC · WHISPER",
            "Tu panel",
            "Dicta con tu atajo en cualquier app, graba tus reuniones y revisa aquí lo que ya quedó guardado.",
        ))

        hero = QHBoxLayout()
        hero.setSpacing(T.BLOCK_GAP)
        root.addLayout(hero)
        hero.addWidget(self._dictation_card(), 5)
        hero.addLayout(self._side_column(), 4)
        root.addWidget(self._stats_row())

        # Tarjetas clicables: cada una lleva a su pestaña.
        panels_host = QWidget()
        panels = CardFlow(250, T.BLOCK_GAP, panels_host)
        panels.setContentsMargins(0, 0, 0, 10)  # aire para la sombra de la última fila
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
        mic = QVBoxLayout(mic_card)
        mic.setContentsMargins(T.CARD_PAD, 16, T.CARD_PAD, 18)
        mic.setSpacing(8)
        level = lambda: ctl.recorder.level  # noqa: E731
        self.orb = MicOrb(level)
        self.orb.setMinimumSize(160, 160)
        self.orb.setFixedHeight(172)
        self.orb.clicked.connect(ctl.toggle_recording)
        self.status = QLabel("Cargando Whisper…")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setProperty("role", "status")
        add_glow(self.status, blur=22, alpha=0.45)
        self.bars = WaveBars(level, height=34)
        hot = QHBoxLayout()
        hot.addStretch(1)
        self.keycaps = KeyCaps(ctl.settings.hotkey)
        hot.addWidget(self.keycaps)
        hot.addStretch(1)
        self.mode_label = label(mode_hint(ctl.settings.mode), "dim", wrap=True)
        self.mode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dictate_btn = QPushButton("Dictar ahora")
        self.dictate_btn.setProperty("variant", "hero")
        self.dictate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dictate_btn.clicked.connect(ctl.toggle_recording)
        # Los stretch dejan el orbe centrado y el botón siempre abajo, sin huecos raros en medio.
        mic.addStretch(1)
        mic.addWidget(self.orb)
        mic.addWidget(self.status)
        mic.addWidget(self.bars)
        mic.addSpacing(6)
        mic.addLayout(hot)
        mic.addWidget(self.mode_label)
        mic.addStretch(1)
        mic.addWidget(self.dictate_btn)
        return mic_card

    def _side_column(self) -> QVBoxLayout:
        side = QVBoxLayout()
        side.setSpacing(T.BLOCK_GAP)

        meeting_card = card()
        mv = QVBoxLayout(meeting_card)
        mv.setContentsMargins(T.CARD_PAD, 18, T.CARD_PAD, 20)
        mv.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(10)
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
        lv.setContentsMargins(T.CARD_PAD, 18, T.CARD_PAD, 18)
        lv.setSpacing(10)
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
        tiles = CardFlow(138, 14, host)
        tiles.setContentsMargins(0, 0, 0, 8)  # aire para la sombra
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
        meetings = self.ctl.meetings.list(limit=20)
        rows = []
        for meeting in meetings[:4]:
            meta = f"{human_date(meeting.created_at)}   ·   {fmt_minutes(meeting.duration)}"
            rows.append(panel_row(meeting.label, meta, meeting.state.capitalize(),
                                  STATE_TONES.get(meeting.state, "muted")))
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
        self.entry, self.ctl = entry, ctl
        v = QVBoxLayout(self)
        v.setContentsMargins(T.CARD_PAD, 16, 16, 18)
        v.setSpacing(8)
        top = QHBoxLayout()
        words = len(entry.text.split())
        meta = f"{human_date(entry.created_at)}   ·   {entry.duration:.0f} s   ·   {words} palabra{'s' if words != 1 else ''}"
        top.addWidget(label(meta, "dim"))
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
        text.setProperty("role", "entry")
        v.addWidget(text)

    def _copy(self) -> None:
        self.ctl.paster.copy(self.entry.text)
        flash_check(self.copy_btn, T.Glyph.COPY)


class HistoryPage(QWidget):
    def __init__(self, ctl: "Controller"):
        super().__init__()
        self.ctl = ctl
        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAGE_MARGIN, 34, T.PAGE_MARGIN, 24)
        root.setSpacing(T.BLOCK_GAP)

        head = QHBoxLayout()
        head.setSpacing(12)
        head.addLayout(page_header("TUS DICTADOS", "Historial"), 1)
        export = icon_button(T.Glyph.EXPORT, "Exportar")
        export.clicked.connect(self._export)
        clear = icon_button(T.Glyph.CLEAR, "Borrar todo", variant="danger")
        clear.clicked.connect(self._clear)
        head.addWidget(export, 0, Qt.AlignmentFlag.AlignBottom)
        head.addWidget(clear, 0, Qt.AlignmentFlag.AlignBottom)
        root.addLayout(head)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar en tu historial…")
        search_icon = self.search.addAction(glyph_icon(T.Glyph.SEARCH), QLineEdit.ActionPosition.LeadingPosition)
        on_restyle(self.search, lambda: search_icon.setIcon(glyph_icon(T.Glyph.SEARCH)))
        self.search.setClearButtonEnabled(True)
        self._debounce = QTimer(self, singleShot=True, interval=180, timeout=self.refresh)
        self.search.textChanged.connect(self._debounce.start)
        root.addWidget(self.search)

        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 2, 10, 6)
        self.list_layout.setSpacing(12)
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
            empty = label(
                "No hay resultados para tu búsqueda." if query else "Aquí aparecerá todo lo que dictes. 🎙",
                "muted",
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(160)
            self.list_layout.addWidget(empty)
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
            title = line.lstrip("#").strip().upper()
            lines.append(f"<div style='color:{T.CYAN}; font-family:Bahnschrift; font-size:9pt; "
                         f"letter-spacing:1px; margin-top:10px;'>{title}</div>")
        elif line.startswith(("-", "*", "•")):
            lines.append(f"<div style='margin-left:6px;'>•&nbsp; {line.lstrip('-*• ')}</div>")
        else:
            lines.append(f"<div>{line}</div>")
    return "".join(lines) + "</div>"


class MeetingCard(QFrame):
    """Una reunión en la lista: cabecera con datos y, al desplegarla, resumen y transcripción."""

    def __init__(self, meeting, ctl: "Controller"):
        super().__init__()
        self.setObjectName("Card")
        self.meeting, self.ctl = meeting, ctl
        self.open = False
        v = QVBoxLayout(self)
        v.setContentsMargins(T.CARD_PAD, 18, 16, 18)
        v.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label(meeting.label, "title"))
        minutes = meeting.duration / 60
        meta = f"{human_date(meeting.created_at)}   ·   {minutes:.0f} min   ·   {meeting.words} palabras"
        titles.addWidget(label(meta, "dim"))
        top.addLayout(titles, 1)

        self.state = label("", "detail")
        set_tone(self.state, STATE_TONES.get(meeting.state, "muted"))
        self.state.setText(meeting.error or meeting.state.capitalize())
        top.addWidget(self.state, 0, Qt.AlignmentFlag.AlignVCenter)

        self.toggle = icon_button(T.Glyph.HISTORY, "Ver", variant="ghost", tooltip="Resumen y transcripción")
        self.toggle.clicked.connect(self._toggle)
        copy_btn = icon_button(T.Glyph.COPY, variant="ghost", tooltip="Copiar el resumen")
        copy_btn.clicked.connect(self._copy)
        export = icon_button(T.Glyph.EXPORT, variant="ghost", tooltip="Guardar como .txt")
        export.clicked.connect(self._export)
        delete = icon_button(T.Glyph.DELETE, variant="ghost", tooltip="Borrar la reunión")
        delete.clicked.connect(self._delete)
        for b in (self.toggle, copy_btn, export, delete):
            top.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        if meeting.state == "error" or (meeting.state == "lista" and not meeting.summary):
            retry = icon_button(T.Glyph.RETRY, variant="ghost", tooltip="Reintentar")
            retry.clicked.connect(lambda: ctl.retry_meeting(meeting.id))
            top.addWidget(retry, 0, Qt.AlignmentFlag.AlignVCenter)
        v.addLayout(top)

        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 8, 0, 0)
        body.setSpacing(6)
        if meeting.summary:
            summary = QLabel()  # texto enriquecido propio: no pasa por WrapLabel
            summary.setWordWrap(True)
            summary.setProperty("role", "body")
            summary.setTextFormat(Qt.TextFormat.RichText)
            on_restyle(summary, lambda text=meeting.summary: summary.setText(summary_html(text)))
            summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            body.addWidget(summary)
            body.addSpacing(10)
        body.addWidget(label("TUS NOTAS", "eyebrow"))
        self.notes = QPlainTextEdit(meeting.notes)
        self.notes.setPlaceholderText("Lo que anotaste en la reunión. Puedes seguir escribiendo aquí.")
        self.notes.setFixedHeight(90)
        self.notes.textChanged.connect(self._save_notes)
        body.addWidget(self.notes)
        body.addSpacing(10)
        body.addWidget(label("TRANSCRIPCIÓN", "eyebrow"))
        text = QPlainTextEdit(meeting.transcript or "Sin transcripción.")
        text.setReadOnly(True)
        text.setMinimumHeight(180)
        body.addWidget(text)
        self.body.hide()
        v.addWidget(self.body)

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
        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAGE_MARGIN, 34, T.PAGE_MARGIN, 24)
        root.setSpacing(T.BLOCK_GAP)

        head = QHBoxLayout()
        head.setSpacing(12)
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
        live_box.setContentsMargins(T.CARD_PAD, 18, T.CARD_PAD, 18)
        live_box.setSpacing(14)
        live_row = QWidget()
        live = QHBoxLayout(live_row)
        live.setContentsMargins(0, 0, 0, 0)
        live.setSpacing(16)
        live_box.addWidget(live_row)
        self.live_dot = StatusDot()
        self.live_dot.state = "recording"
        live.addWidget(self.live_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.live_title = label("Grabando reunión", "title")
        self.live_detail = label("", "dim")
        texts.addWidget(self.live_title)
        texts.addWidget(self.live_detail)
        live.addLayout(texts, 1)
        self.live_bars = WaveBars(lambda: ctl.meeting_recorder.level, height=34)
        live.addWidget(self.live_bars, 1)

        # Qué se está grabando: se puede silenciar cada fuente en caliente.
        self.source_buttons: dict[str, QPushButton] = {}
        picker = QWidget()
        pl = QHBoxLayout(picker)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
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
        panel = QHBoxLayout()
        panel.setSpacing(16)
        transcript_box = QVBoxLayout()
        transcript_box.setSpacing(4)
        transcript_box.addWidget(label("EN VIVO", "eyebrow"))
        self.live_view = QPlainTextEdit()
        self.live_view.setReadOnly(True)
        self.live_view.setFixedHeight(120)
        self.live_view.setPlaceholderText("La transcripción aparecerá aquí cada ~30 segundos…")
        transcript_box.addWidget(self.live_view)
        panel.addLayout(transcript_box, 1)
        notes_box = QVBoxLayout()
        notes_box.setSpacing(4)
        notes_box.addWidget(label("TUS NOTAS", "eyebrow"))
        self.notes_view = QPlainTextEdit()
        self.notes_view.setFixedHeight(120)
        self.notes_view.setPlaceholderText("Apunta lo que importa: entra en el resumen final.")
        self.notes_view.textChanged.connect(lambda: ctl.set_meeting_notes(self.notes_view.toPlainText()))
        notes_box.addWidget(self.notes_view)
        panel.addLayout(notes_box, 1)
        live_box.addLayout(panel)
        self.live.hide()
        root.addWidget(self.live)
        self._clock = QTimer(self, interval=1000, timeout=self._tick)

        # Preguntar a tus reuniones, con el modelo local.
        self.ask_card = card()
        ask_box = QVBoxLayout(self.ask_card)
        ask_box.setContentsMargins(T.CARD_PAD, 18, T.CARD_PAD, 18)
        ask_box.setSpacing(10)
        ask_row = QHBoxLayout()
        ask_row.setSpacing(10)
        self.ask_input = QLineEdit()
        self.ask_input.setPlaceholderText("Pregúntale a tus reuniones: «¿qué quedó pendiente para mí?»")
        self.ask_input.returnPressed.connect(self._ask)
        ask_btn = icon_button(T.Glyph.BOLT, "Preguntar", variant="primary")
        ask_btn.clicked.connect(self._ask)
        ask_row.addWidget(self.ask_input, 1)
        ask_row.addWidget(ask_btn)
        ask_box.addLayout(ask_row)
        self.answer = label("", "muted", wrap=True)
        self.answer.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.answer.hide()
        ask_box.addWidget(self.answer)
        root.addWidget(self.ask_card)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar en tus reuniones…")
        search_icon = self.search.addAction(glyph_icon(T.Glyph.SEARCH), QLineEdit.ActionPosition.LeadingPosition)
        on_restyle(self.search, lambda: search_icon.setIcon(glyph_icon(T.Glyph.SEARCH)))
        self.search.setClearButtonEnabled(True)
        self._debounce = QTimer(self, singleShot=True, interval=180, timeout=self.refresh)
        self.search.textChanged.connect(self._debounce.start)
        root.addWidget(self.search)

        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 2, 10, 6)
        self.list_layout.setSpacing(12)
        root.addWidget(scrollable(self.list_host), 1)
        self.refresh()

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
            card_widget.state.setText(text)
            set_tone(card_widget.state, "accent")

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
            empty = label(
                "No hay resultados para tu búsqueda." if query else
                "Aquí aparecerán tus reuniones. Actívalas en Ajustes › Reuniones. 🎧", "muted")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(160)
            self.list_layout.addWidget(empty)
        for meeting in meetings:
            card_widget = MeetingCard(meeting, self.ctl)
            self.cards[meeting.id] = card_widget
            self.list_layout.addWidget(card_widget)
        self.list_layout.addStretch(1)


# --- Modelos ------------------------------------------------------------------
class ModelRow(QWidget):
    def __init__(self, key: str, ctl: "Controller", summary: bool = False):
        super().__init__()
        self.key, self.ctl, self.summary = key, ctl, summary
        name, _, desc = (SUMMARY_MODELS if summary else MODELS)[key].partition(" · ")
        self.name = name
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 12, 0, 12)
        v.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
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
        self.detail = label("", "detail")
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
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setContentsMargins(T.PAGE_MARGIN, 34, T.PAGE_MARGIN - 8, 36)
        root.setSpacing(T.BLOCK_GAP)
        root.addLayout(page_header("CONFIGURACIÓN", "Ajustes", "Los cambios se guardan al instante."))

        # Atajo
        sec = self._section(root, T.Glyph.KEYBOARD, "Atajo de teclado")
        hot = QWidget()
        hl = QHBoxLayout(hot)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(12)
        self.keycaps = KeyCaps(s.hotkey)
        self.capture_btn = icon_button(T.Glyph.KEYBOARD, "Cambiar atajo")
        self.capture_btn.clicked.connect(self._toggle_capture)
        hl.addWidget(self.keycaps)
        hl.addWidget(self.capture_btn)
        self._row(sec, "Combinación", "Funciona en cualquier app, aunque NeonWhisper esté minimizado.", hot)
        self.capture_msg = label("", "dim", wrap=True)
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
        self.prompt.setMinimumWidth(300)
        self.prompt.editingFinished.connect(lambda: ctl.update_setting("initial_prompt", self.prompt.text()))
        self._row(sec, "Vocabulario", "Nombres y términos que Whisper debe escribir bien.", self.prompt, last=True)

        # Modelos
        sec = self._section(root, T.Glyph.DOWNLOAD, "Modelos de Whisper")
        sec.addWidget(label(
            "Large v3 Turbo es casi tan preciso como Large v3 y varias veces más rápido. "
            "Puedes pausar una descarga y continuarla después, incluso si cierras la app.", "dim", wrap=True))
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
        mh.setSpacing(10)
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
        mp.setContentsMargins(0, 0, 0, 14)
        mp.setSpacing(16)
        self.mic_bars = WaveBars(lambda: self.mic_tester.level, height=40)
        self.mic_status = label("", "micstatus", wrap=True)
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
        slider = NoWheelSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(int(s.sound_volume * 100))
        slider.setFixedWidth(200)
        slider.sliderReleased.connect(lambda: ctl.update_setting("sound_volume", slider.value() / 100))
        test = icon_button(T.Glyph.PLAY, "Probar")
        test.clicked.connect(ctl.test_sound)
        vl.addWidget(slider)
        vl.addWidget(test)
        self._row(sec, "Volumen de sonidos", "", vol, last=True)

        # Reuniones
        sec = self._section(root, T.Glyph.HISTORY, "Reuniones")
        sec.addWidget(label(
            "NeonWhisper mira si una app de reuniones (Teams, Zoom, Meet, Webex, Discord…) está usando tu "
            "micrófono. Cuando eso pasa, graba tu voz y lo que suena en tu PC, y al terminar transcribe y "
            "resume, todo en tu computadora. Avisa a los demás de que estás grabando: en muchos sitios es "
            "obligatorio.", "dim", wrap=True))
        sec.addSpacing(10)
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
        ah.setSpacing(10)
        self.meeting_bars = WaveBars(lambda: self.meeting_audio.level, height=34)
        self.meeting_bars.setFixedWidth(150)
        self.meeting_test_btn = icon_button(T.Glyph.PLAY, "Probar")
        self.meeting_test_btn.clicked.connect(self._toggle_meeting_audio_test)
        ah.addWidget(self.meeting_bars)
        ah.addWidget(self.meeting_test_btn)
        self._row(sec, "Probar qué se grabaría",
                  "Cinco segundos escuchando las dos fuentes: habla y deja sonando un video.", audio_host)
        self.meeting_audio_status = label("", "micstatus", wrap=True)
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
        sec.addWidget(label("El tema pinta toda la app: fondos, acentos, el orbe del micrófono y el ícono. "
                            "El cambio es inmediato, no hace falta reiniciar.", "dim", wrap=True))
        sec.addSpacing(10)
        theme_host = QWidget()
        theme_cards = CardFlow(186, 12, theme_host)
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
        sec.addSpacing(14)
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
        dv.setContentsMargins(0, 12, 0, 14)
        dv.setSpacing(4)
        dv.addWidget(label("Diseño", "title"))
        dv.addWidget(label("Al cambiar cualquier opción, la barra aparece unos segundos para que veas cómo queda.", "dim",
                           wrap=True))
        dv.addSpacing(8)
        cards_host = QWidget()
        cards = CardFlow(186, 12, cards_host)
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
        al.setSpacing(10)
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
        open_data = icon_button(T.Glyph.FOLDER, "Historial y ajustes")
        open_data.clicked.connect(lambda: os.startfile(DATA_DIR))
        open_models = icon_button(T.Glyph.FOLDER, "Modelos")
        open_models.clicked.connect(lambda: os.startfile(MODELS_DIR))
        fl.addWidget(open_data)
        fl.addWidget(open_models)
        self._row(sec, "Carpetas", f"NeonWhisper v{__version__} · todo se guarda en tu PC.", folders, last=True)
        root.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrollable(inner))

    # --- helpers -------------------------------------------------------------
    @staticmethod
    def _section(root: QVBoxLayout, glyph: str, title: str) -> QVBoxLayout:
        frame = card()
        v = QVBoxLayout(frame)
        v.setContentsMargins(T.CARD_PAD, 20, T.CARD_PAD, 12)
        v.setSpacing(0)
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(GlyphLabel(glyph, "CYAN", 18))
        head.addWidget(label(title, "h2"))
        head.addStretch(1)
        v.addLayout(head)
        v.addSpacing(6)
        root.addWidget(frame)
        return v

    @staticmethod
    def _row(section: QVBoxLayout, title: str, desc: str, control: QWidget, last: bool = False) -> None:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 14, 0, 14)
        h.setSpacing(26)
        text = QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(label(title, "title"))
        if desc:
            text.addWidget(label(desc, "dim", wrap=True))
        h.addLayout(text, 1)
        h.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        section.addWidget(row)
        if not last:
            section.addWidget(separator())

    # --- barra flotante -------------------------------------------------------
    def _percent_slider(self, value: float, lo: int, hi: int, key: str) -> QWidget:
        host = QWidget()
        h = QHBoxLayout(host)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)
        slider = NoWheelSlider(Qt.Orientation.Horizontal)
        slider.setRange(lo, hi)
        slider.setPageStep(10)
        slider.setFixedWidth(220)
        pct = label("", "pct")
        pct.setFixedWidth(46)
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
        self.resize(1140, 760)
        self.setMinimumSize(960, 660)
        self._titlebar_done = False

        root = QWidget()
        root.setObjectName("Root")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(252)
        sv = QVBoxLayout(sidebar)
        sv.setContentsMargins(20, 26, 20, 20)
        sv.setSpacing(8)
        brand = QHBoxLayout()
        brand.setSpacing(12)
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
        sv.addSpacing(26)

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
        st.setContentsMargins(16, 14, 16, 14)
        st.setSpacing(10)
        self.dot = StatusDot()
        st.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        self.model_title = label("Preparando…", "strong")
        self.model_detail = label("", "dim", wrap=True)
        texts.addWidget(self.model_title)
        texts.addWidget(self.model_detail)
        self.dl_label = label("", "dlstatus", wrap=True)
        self.dl_bar = NeonProgress(6)
        texts.addSpacing(6)
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
        if self.isVisible():
            T.apply_titlebar(int(self.winId()))

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
