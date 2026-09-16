"""Ventana principal: Inicio, Historial y Ajustes."""
import os
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QShowEvent
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QStackedWidget, QVBoxLayout, QWidget,
)

from neonwhisper import __version__
from neonwhisper.audio import device_name, list_input_devices, resolve_input_device
from neonwhisper.config import LANGUAGES, MODEL_SIZES, MODELS
from neonwhisper.fmt import fmt_bytes, fmt_eta, fmt_speed
from neonwhisper.history import Entry
from neonwhisper.mictest import MicTester
from neonwhisper.paths import DATA_DIR, MODELS_DIR
from neonwhisper.ui import theme as T
from neonwhisper.ui.widgets import (
    GlyphLabel, KeyCaps, Logo, MicOrb, NeonProgress, OverlayStyleCard, StatusDot, ToggleSwitch, WaveBars, add_glow,
    card, glyph_icon, label, make_app_icon,
)
from neonwhisper.ui.overlay_styles import STYLES

if TYPE_CHECKING:
    from neonwhisper.app import Controller

MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


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
    box.setSpacing(4)
    box.addWidget(label(eyebrow, "eyebrow"))
    h1 = label(title, "h1")
    box.addWidget(h1)
    if subtitle:
        box.addWidget(label(subtitle, "muted", wrap=True))
    return box


def icon_button(glyph: str, text: str = "", variant: str | None = None, tooltip: str = "") -> QPushButton:
    btn = QPushButton(text)
    btn.setIcon(glyph_icon(glyph, color=T.MUTED if variant != "primary" else "#021018", hover=T.ICE))
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
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {T.LINE};")
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
class HomePage(QWidget):
    def __init__(self, ctl: "Controller"):
        super().__init__()
        self.ctl = ctl
        root = QVBoxLayout(self)
        root.setContentsMargins(44, 34, 44, 30)
        root.setSpacing(18)
        root.addLayout(page_header(
            "DICTADO LOCAL · WHISPER",
            "Habla. Se escribe solo.",
            "Presiona tu atajo en cualquier aplicación, dicta y el texto aparece donde está tu cursor.",
        ))

        body = QHBoxLayout()
        body.setSpacing(22)
        root.addLayout(body, 1)

        # Columna del micrófono
        mic_card = card(glow=True)
        mic = QVBoxLayout(mic_card)
        mic.setContentsMargins(24, 10, 24, 22)
        mic.setSpacing(8)
        level = lambda: ctl.recorder.level  # noqa: E731
        self.orb = MicOrb(level)
        self.orb.setFixedHeight(300)
        self.orb.clicked.connect(ctl.toggle_recording)
        self.status = QLabel("Cargando Whisper…")
        self.status.setFont(T.display_font(15))
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet(f"color: {T.ICE};")
        add_glow(self.status, blur=22, alpha=0.45)
        self.bars = WaveBars(level, height=46)
        hot = QHBoxLayout()
        hot.addStretch(1)
        self.keycaps = KeyCaps(ctl.settings.hotkey)
        hot.addWidget(self.keycaps)
        hot.addStretch(1)
        self.mode_label = label(mode_hint(ctl.settings.mode), "dim")
        self.mode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mic.addStretch(1)
        mic.addWidget(self.orb)
        mic.addWidget(self.status)
        mic.addSpacing(4)
        mic.addWidget(self.bars)
        mic.addSpacing(14)
        mic.addLayout(hot)
        mic.addWidget(self.mode_label)
        mic.addStretch(1)
        body.addWidget(mic_card, 5)

        # Columna lateral
        side_host = QWidget()
        side_host.setMinimumWidth(300)
        side = QVBoxLayout(side_host)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(16)
        body.addWidget(side_host, 3)

        stats = card()
        grid = QHBoxLayout(stats)
        grid.setContentsMargins(20, 14, 20, 14)
        grid.setSpacing(12)
        self.stat_count = label("0", "stat")
        self.stat_words = label("0", "stat")
        self.stat_speed = label("—", "stat")
        for title, value in (("DICTADOS", self.stat_count), ("PALABRAS", self.stat_words), ("LATENCIA", self.stat_speed)):
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(label(title, "mini"))
            col.addWidget(value)
            grid.addLayout(col, 1)
        side.addWidget(stats)

        last = card()
        lv = QVBoxLayout(last)
        lv.setContentsMargins(20, 16, 20, 16)
        lv.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(label("ÚLTIMA TRANSCRIPCIÓN", "eyebrow"))
        top.addStretch(1)
        self.copy_last = icon_button(T.Glyph.COPY, variant="ghost", tooltip="Copiar")
        self.copy_last.clicked.connect(self._copy_last)
        top.addWidget(self.copy_last)
        lv.addLayout(top)
        self.last_text = label("Todavía no has dictado nada. Prueba tu atajo o haz clic en el micrófono.", "muted", wrap=True)
        self.last_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.last_text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.last_text.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        lv.addWidget(self.last_text, 1)
        side.addWidget(last, 1)

        tips = card()
        tv = QVBoxLayout(tips)
        tv.setContentsMargins(20, 14, 20, 14)
        tv.setSpacing(6)
        tv.addWidget(label("TIPS", "eyebrow"))
        for tip in (
            "Esc cancela la grabación.",
            "Todo corre en tu PC: tu voz no sale a internet.",
            "Agrega nombres propios en Ajustes › Vocabulario.",
        ):
            tv.addWidget(label(f"›  {tip}", "muted", wrap=True))
        side.addWidget(tips)
        self._last = ""

    def set_state(self, state: str, text: str) -> None:
        self.orb.set_state(state)
        self.bars.set_mode({"recording": "recording", "processing": "processing"}.get(state, "idle"))
        self.status.setText(text)

    def set_last(self, text: str) -> None:
        self._last = text
        self.last_text.setText(text)
        self.last_text.setProperty("role", None)
        self.last_text.setStyleSheet(f"color: {T.TEXT}; font-size: 11pt;")

    def set_stats(self, count: int, words: int, seconds: float | None) -> None:
        self.stat_count.setText(f"{count:,}")
        self.stat_words.setText(f"{words:,}")
        if seconds is not None:
            self.stat_speed.setText(f"{seconds:.1f}s")

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
        v.setContentsMargins(20, 12, 12, 14)
        v.setSpacing(6)
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
        text.setStyleSheet(f"color: {T.TEXT}; font-size: 10.5pt;")
        v.addWidget(text)

    def _copy(self) -> None:
        self.ctl.paster.copy(self.entry.text)
        flash_check(self.copy_btn, T.Glyph.COPY)


class HistoryPage(QWidget):
    def __init__(self, ctl: "Controller"):
        super().__init__()
        self.ctl = ctl
        root = QVBoxLayout(self)
        root.setContentsMargins(44, 34, 44, 20)
        root.setSpacing(16)

        head = QHBoxLayout()
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
        self.search.addAction(glyph_icon(T.Glyph.SEARCH), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self._debounce = QTimer(self, singleShot=True, interval=180, timeout=self.refresh)
        self.search.textChanged.connect(self._debounce.start)
        root.addWidget(self.search)

        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 8, 0)
        self.list_layout.setSpacing(10)
        root.addWidget(scrollable(self.list_host), 1)
        self.refresh()

    def refresh(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
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


# --- Modelos ------------------------------------------------------------------
class ModelRow(QWidget):
    def __init__(self, key: str, ctl: "Controller"):
        super().__init__()
        self.key, self.ctl = key, ctl
        name, _, desc = MODELS[key].partition(" · ")
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
        title = QLabel(name)
        title.setStyleSheet(f"font-size: 10.5pt; font-weight: 600; color: {T.TEXT};")
        self.badge = QLabel("EN USO")
        self.badge.setStyleSheet(
            f"color: #021018; background: {T.CYAN}; border-radius: 8px; padding: 1px 8px;"
            "font-family: Bahnschrift; font-size: 8pt; font-weight: 600;"
        )
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
        self.detail = QLabel()
        v.addWidget(self.bar)
        v.addWidget(self.detail)
        self.refresh()

    def refresh(self) -> None:
        info = self.ctl.downloads.info(self.key)
        state = info.state
        in_use = state == "installed" and self.ctl.settings.model == self.key
        self.badge.setVisible(in_use)
        visible = {
            self.btn_use: state == "installed" and not in_use,
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
        color = T.DANGER if state == "error" else (T.ICE if state == "downloading" else T.MUTED)
        self.detail.setStyleSheet(f"color: {color}; font-size: 9pt;")

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
        root.setContentsMargins(44, 34, 36, 34)
        root.setSpacing(18)
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
        self.mic_status = QLabel()
        self.mic_status.setWordWrap(True)
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

        # Barra flotante
        sec = self._section(root, T.Glyph.PALETTE, "Barra flotante")
        self._row(sec, "Mostrar barra flotante", "La barra de voz que aparece sobre tus apps mientras dictas.",
                  self._toggle(s.show_overlay, lambda v: ctl.update_setting("show_overlay", v)))
        design = QWidget()
        dv = QVBoxLayout(design)
        dv.setContentsMargins(0, 12, 0, 14)
        dv.setSpacing(4)
        title = QLabel("Diseño")
        title.setStyleSheet(f"font-size: 10.5pt; font-weight: 600; color: {T.TEXT};")
        dv.addWidget(title)
        dv.addWidget(label("Al cambiar cualquier opción, la barra aparece unos segundos para que veas cómo queda.", "dim",
                           wrap=True))
        dv.addSpacing(8)
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.style_group = QButtonGroup(self)
        self.style_cards: dict[str, OverlayStyleCard] = {}
        for key in STYLES:
            c = OverlayStyleCard(key, s)
            c.setChecked(key == s.overlay_style)
            c.clicked.connect(lambda _=False, k=key: self._set_overlay("overlay_style", k))
            self.style_group.addButton(c)
            self.style_cards[key] = c
            cards.addWidget(c)
        dv.addLayout(cards)
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
        v.setContentsMargins(22, 16, 22, 8)
        v.setSpacing(0)
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(GlyphLabel(glyph, T.CYAN, 18))
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
        h.setContentsMargins(0, 12, 0, 12)
        h.setSpacing(24)
        text = QVBoxLayout()
        text.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet(f"font-size: 10.5pt; font-weight: 600; color: {T.TEXT};")
        text.addWidget(t)
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
        pct = QLabel()
        pct.setFixedWidth(46)
        pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        pct.setStyleSheet(f"color: {T.ICE}; font-family: Bahnschrift; font-size: 10.5pt; font-weight: 600;")

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

    def refresh_models(self, key: str | None = None) -> None:
        for k, row in self.model_rows.items():
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

    def _on_mic_test(self, state: str, message: str) -> None:
        active = state in ("recording", "playing")
        self.mic_bars.set_mode("recording" if active else "idle")
        self.mic_test_btn.setText("Detener" if active else "Probar otra vez")
        color = {"ok": T.OK, "silent": T.DANGER, "error": T.DANGER}.get(state, T.ICE if active else T.MUTED)
        self.mic_status.setStyleSheet(f"color: {color}; font-size: 10pt;")
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
        sidebar.setFixedWidth(236)
        sv = QVBoxLayout(sidebar)
        sv.setContentsMargins(18, 24, 18, 18)
        sv.setSpacing(6)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        self.logo = Logo(36)
        brand.addWidget(self.logo)
        name = QLabel(f"<span style='color:{T.ICE}'>NEON</span><span style='color:{T.TEXT}'>WHISPER</span>")
        name.setFont(T.display_font(14))
        add_glow(name, blur=24, alpha=0.5)
        brand.addWidget(name)
        brand.addStretch(1)
        sv.addLayout(brand)
        sv.addSpacing(26)

        self.stack = QStackedWidget()
        self.home = HomePage(ctl)
        self.history = HistoryPage(ctl)
        self.settings = SettingsPage(ctl)
        nav_group = QButtonGroup(self)
        for i, (glyph, text, page) in enumerate((
            (T.Glyph.HOME, "Inicio", self.home),
            (T.Glyph.HISTORY, "Historial", self.history),
            (T.Glyph.SETTINGS, "Ajustes", self.settings),
        )):
            self.stack.addWidget(page)
            btn = QPushButton(f"   {text}")
            btn.setObjectName("NavButton")
            btn.setIcon(glyph_icon(glyph))
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, idx=i: self.stack.setCurrentIndex(idx))
            nav_group.addButton(btn)
            sv.addWidget(btn)
        self.nav_buttons = nav_group.buttons()
        sv.addStretch(1)

        status = card()
        st = QHBoxLayout(status)
        st.setContentsMargins(12, 12, 12, 12)
        st.setSpacing(8)
        self.dot = StatusDot()
        st.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        self.model_title = QLabel("Preparando…")
        self.model_title.setStyleSheet(f"font-weight: 600; color: {T.TEXT};")
        self.model_detail = label("", "dim", wrap=True)
        texts.addWidget(self.model_title)
        texts.addWidget(self.model_detail)
        self.dl_label = QLabel()
        self.dl_label.setWordWrap(True)
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
            color = T.DANGER if mode == "error" else (T.ICE if mode in ("active", "indeterminate") else T.MUTED)
            self.dl_label.setStyleSheet(f"color: {color}; font-size: 8.5pt;")
            self.dl_label.setText(text)
            self.dl_bar.set_progress(fraction, mode)

    def set_recording_indicator(self, recording: bool) -> None:
        self.logo.active = recording
        self.logo.update()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._titlebar_done:
            T.apply_dark_titlebar(int(self.winId()))
            self._titlebar_done = True

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.ctl.quitting:
            event.accept()
            return
        event.ignore()
        self.hide()
        self.ctl.on_window_hidden()
