"""Paleta neón azul/negro, tipografías, hoja de estilos y barra de título oscura nativa."""
import ctypes
import sys

from PySide6.QtGui import QColor, QFont, QFontDatabase

# --- Paleta -------------------------------------------------------------------
BG0 = "#03050b"      # fondo más profundo
BG1 = "#060a14"      # barra lateral
BG2 = "#08101f"      # tarjetas
BG3 = "#0c1628"      # hover / inputs
LINE = "#12203d"
LINE_HI = "#1b3363"
TEXT = "#e6f1ff"
MUTED = "#7d8bb0"
DIM = "#4a5878"
CYAN = "#00e5ff"
ICE = "#7df9ff"
BLUE = "#2d7dff"
INDIGO = "#5b5bff"
DANGER = "#ff4d7a"
OK = "#3dffc5"


def qc(hex_color: str, alpha: float = 1.0) -> QColor:
    c = QColor(hex_color)
    c.setAlphaF(alpha)
    return c


# --- Tipografías --------------------------------------------------------------
_icon_family: str | None = None


def icon_family() -> str:
    global _icon_family
    if _icon_family is None:
        families = set(QFontDatabase.families())
        _icon_family = next(
            (f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in families), "Segoe UI Symbol"
        )
    return _icon_family


def display_font(size: float, weight: QFont.Weight = QFont.Weight.DemiBold) -> QFont:
    f = QFont("Bahnschrift", 1)
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


def icon_font(size: float) -> QFont:
    f = QFont(icon_family())
    f.setPointSizeF(size)
    return f


class Glyph:
    HOME = ""
    HISTORY = ""
    SETTINGS = ""
    MIC = ""
    COPY = ""
    DELETE = ""
    SEARCH = ""
    KEYBOARD = ""
    GLOBE = ""
    VOLUME = ""
    CANCEL = ""
    CHECK = ""
    FOLDER = ""
    BOLT = ""
    PASTE = ""
    EXPORT = ""
    PLAY = ""
    PAUSE = ""
    DOWNLOAD = ""
    RETRY = ""
    CLEAR = ""


# --- Hoja de estilos ----------------------------------------------------------
STYLESHEET = f"""
* {{ outline: none; }}
QWidget {{ color: {TEXT}; font-family: "Segoe UI Variable Text", "Segoe UI"; font-size: 10pt; }}
QMainWindow, #Root {{ background: {BG0}; }}
#Sidebar {{ background: {BG1}; border-right: 1px solid {LINE}; }}
#Page, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}

QLabel {{ background: transparent; }}
QLabel[role="h1"] {{ font-family: "Bahnschrift"; font-size: 24pt; font-weight: 600; color: {TEXT}; }}
QLabel[role="h2"] {{ font-family: "Bahnschrift"; font-size: 13pt; font-weight: 600; color: {TEXT}; }}
QLabel[role="eyebrow"] {{ font-family: "Bahnschrift"; font-size: 8.5pt; font-weight: 600; color: {CYAN}; letter-spacing: 2px; padding-top: 3px; }}
QLabel[role="mini"] {{ font-family: "Bahnschrift"; font-size: 8pt; font-weight: 600; color: {CYAN}; letter-spacing: 1px; padding-top: 3px; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="dim"] {{ color: {DIM}; font-size: 9pt; }}
QLabel[role="stat"] {{ font-family: "Bahnschrift"; font-size: 20pt; font-weight: 600; color: {ICE}; }}
QLabel[role="icon"] {{ color: {CYAN}; }}

#Card {{ background: {BG2}; border: 1px solid {LINE}; border-radius: 14px; }}
#Card[glow="true"] {{ border: 1px solid rgba(0, 229, 255, 0.28); }}

QPushButton {{
    background: {BG3}; border: 1px solid {LINE_HI}; border-radius: 10px;
    padding: 8px 16px; color: {TEXT};
}}
QPushButton:hover {{ border-color: {CYAN}; color: {ICE}; background: #0e1c36; }}
QPushButton:pressed {{ background: #0a1428; }}
QPushButton:disabled {{ color: {DIM}; border-color: {LINE}; }}
QPushButton[variant="primary"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {BLUE}, stop:1 #00b8e6);
    border: 1px solid rgba(125, 249, 255, 0.55); color: #021018; font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #4a90ff, stop:1 {CYAN}); color: #000; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; color: {MUTED}; padding: 6px 10px; }}
QPushButton[variant="ghost"]:hover {{ color: {ICE}; background: {BG3}; border-color: {LINE_HI}; }}
QPushButton[variant="danger"]:hover {{ border-color: {DANGER}; color: {DANGER}; }}

QPushButton#NavButton {{
    text-align: left; padding: 11px 14px; border-radius: 10px; font-size: 10.5pt;
    color: {MUTED}; background: transparent; border: 1px solid transparent;
}}
QPushButton#NavButton:hover {{ background: {BG3}; color: #cfe9ff; }}
QPushButton#NavButton:checked {{
    color: {ICE}; border: 1px solid rgba(0, 229, 255, 0.35);
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(0,229,255,0.16), stop:1 rgba(45,125,255,0.03));
}}

QPushButton#Segment {{ border-radius: 0; padding: 8px 16px; color: {MUTED}; background: {BG3}; font-weight: 600; }}
QPushButton#Segment:checked {{ color: #021018; font-weight: 600; background: {CYAN}; border-color: {CYAN}; }}
QPushButton#Segment[pos="first"] {{ border-top-left-radius: 10px; border-bottom-left-radius: 10px; }}
QPushButton#Segment[pos="last"] {{ border-top-right-radius: 10px; border-bottom-right-radius: 10px; }}

QLineEdit, QPlainTextEdit {{
    background: #050912; border: 1px solid {LINE_HI}; border-radius: 10px;
    padding: 8px 12px; selection-background-color: {BLUE}; color: {TEXT};
}}
QLineEdit:focus, QPlainTextEdit:focus {{ border-color: {CYAN}; }}

QComboBox {{
    background: #050912; border: 1px solid {LINE_HI}; border-radius: 10px;
    padding: 7px 12px; min-width: 240px; color: {TEXT};
}}
QComboBox:hover, QComboBox:focus {{ border-color: {CYAN}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: none; width: 0; }}
QComboBox QAbstractItemView {{
    background: {BG2}; border: 1px solid {LINE_HI}; padding: 4px;
    selection-background-color: #0f2a55; selection-color: {ICE}; outline: none;
}}

QSlider::groove:horizontal {{ height: 4px; background: {LINE_HI}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {BLUE}, stop:1 {CYAN}); border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; background: #e9fcff; border: 2px solid {CYAN}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {LINE_HI}; border-radius: 3px; min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(0, 229, 255, 0.5); }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}

QToolTip {{ background: {BG2}; color: {ICE}; border: 1px solid {LINE_HI}; padding: 6px 8px; border-radius: 6px; }}
QMenu {{ background: {BG2}; border: 1px solid {LINE_HI}; padding: 6px; }}
QMenu::item {{ padding: 8px 22px; border-radius: 6px; color: {TEXT}; }}
QMenu::item:selected {{ background: #0f2a55; color: {ICE}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 6px 8px; }}
QMessageBox {{ background: {BG1}; }}
"""


def apply_dark_titlebar(hwnd: int) -> None:
    """Barra de título negra con borde neón (Windows 11; en Windows 10 solo modo oscuro)."""
    if sys.platform != "win32":
        return
    dwm = ctypes.windll.dwmapi

    def set_attr(attr: int, value: int) -> None:
        v = ctypes.c_int(value)
        dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v))

    def colorref(hex_color: str) -> int:
        c = QColor(hex_color)
        return c.red() | (c.green() << 8) | (c.blue() << 16)

    set_attr(20, 1)                       # DWMWA_USE_IMMERSIVE_DARK_MODE
    set_attr(35, colorref(BG1))           # DWMWA_CAPTION_COLOR
    set_attr(34, colorref("#0b6f8c"))     # DWMWA_BORDER_COLOR
    set_attr(36, colorref(ICE))           # DWMWA_TEXT_COLOR
