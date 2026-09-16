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
from neonwhisper.audio import device_name, list_input_devices
from neonwhisper.config import LANGUAGES, MODEL_SIZES, MODELS
from neonwhisper.history import Entry
from neonwhisper.paths import DATA_DIR, MODELS_DIR, model_downloaded
from neonwhisper.ui import theme as T
from neonwhisper.ui.widgets import (
    GlyphLabel, KeyCaps, Logo, MicOrb, StatusDot, ToggleSwitch, WaveBars, add_glow, card, glyph_icon, label,
    make_app_icon,
)

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
        box = QMessageBox(self)
        box.setWindowTitle("Borrar historial")
        box.setText("¿Borrar todo el historial? Esta acción no se puede deshacer.")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        box.button(QMessageBox.StandardButton.Yes).setText("Borrar todo")
        box.button(QMessageBox.StandardButton.Cancel).setText("Cancelar")
        if box.exec() == QMessageBox.StandardButton.Yes:
            self.ctl.clear_history()


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
        self.model_combo = self._combo(MODELS, s.model, self._on_model_selected)
        self.refresh_model_labels()
        self._row(sec, "Modelo", "Large v3 Turbo es casi tan preciso como Large v3 y varias veces más rápido.",
                  self.model_combo)
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
        self._row(sec, "Micrófono", "El dispositivo que se usa para grabar.", self.mic_combo)
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

        # Comportamiento
        sec = self._section(root, T.Glyph.PASTE, "Comportamiento")
        self._row(sec, "Pegar automáticamente", "Si lo apagas, el texto solo se copia al portapapeles.",
                  self._toggle(s.auto_paste, lambda v: ctl.update_setting("auto_paste", v)))
        self._row(sec, "Restaurar portapapeles", "Después de pegar, vuelve a dejar lo que tenías copiado.",
                  self._toggle(s.restore_clipboard, lambda v: ctl.update_setting("restore_clipboard", v)))
        self._row(sec, "Barra flotante", "Muestra la barra de voz sobre tus apps mientras dictas.",
                  self._toggle(s.show_overlay, lambda v: ctl.update_setting("show_overlay", v)))
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
            line = QFrame()
            line.setFixedHeight(1)
            line.setStyleSheet(f"background: {T.LINE};")
            section.addWidget(line)

    def refresh_model_labels(self) -> None:
        for i in range(self.model_combo.count()):
            key = self.model_combo.itemData(i)
            suffix = "  ✓ instalado" if model_downloaded(key) else f"  · descargar {MODEL_SIZES.get(key, '')}"
            self.model_combo.setItemText(i, MODELS[key] + suffix)

    def _on_model_selected(self, key: str) -> None:
        if key == self.ctl.settings.model:
            return
        if not model_downloaded(key):
            box = QMessageBox(self)
            box.setWindowTitle("Descargar modelo")
            box.setText(
                f"«{MODELS[key].split(' · ')[0]}» no está instalado ({MODEL_SIZES.get(key, '')}).\n\n"
                "¿Descargarlo ahora? Mientras se descarga puedes seguir dictando con el modelo actual."
            )
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
            box.button(QMessageBox.StandardButton.Yes).setText("Descargar")
            box.button(QMessageBox.StandardButton.Cancel).setText("Cancelar")
            if box.exec() != QMessageBox.StandardButton.Yes:
                self.model_combo.blockSignals(True)
                self.model_combo.setCurrentIndex(self.model_combo.findData(self.ctl.settings.model))
                self.model_combo.blockSignals(False)
                return
        self.ctl.update_setting("model", key)

    def _on_mic_selected(self, _index: int) -> None:
        self.ctl.update_setting("input_device", None)
        self.ctl.update_setting("input_device_name", self.mic_combo.currentData() or "")

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
