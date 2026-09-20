"""Temas de la interfaz (Neón, Cristal, Sutil y Pastel), tipografías, hoja de estilos y barra de título nativa.

Los colores viven en `THEMES` y se copian a las constantes del módulo (`T.CYAN`, `T.BG0`…) cada vez
que se aplica un tema, para que todo el código siga leyéndolas igual. Los widgets que pintan a mano
las leen en cada `paintEvent`, así que cambian solos; el resto se refresca con `ui.widgets.restyle`.
"""
import ctypes
import sys
from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QFontDatabase


@dataclass(frozen=True)
class UITheme:
    key: str
    name: str
    description: str
    # Superficies
    bg0: str          # fondo de la ventana
    bg1: str          # barra lateral
    bg2: str          # tarjetas
    bg3: str          # hover / botones
    line: str
    line_hi: str
    input_bg: str
    select_bg: str    # selección en menús y listas
    hover_bg: str
    press_bg: str
    # Texto
    text: str
    muted: str
    dim: str
    nav_hover: str
    on_accent: str    # texto sobre un relleno del color de acento
    # Acentos
    accent: str       # color principal (CYAN)
    ice: str          # variante brillante del acento
    blue: str
    indigo: str
    danger: str
    ok: str
    # Botón primario
    primary_from: str
    primary_to: str
    primary_hover_from: str
    primary_hover_to: str
    # Detalles
    keycap_bg: str
    keycap_edge: str
    titlebar_border: str
    logo_idle: str
    logo_active: str
    orb_hi: str       # centro del orbe mientras grabas
    orb_hi2: str
    orb_idle: str
    orb_mid: str
    orb_deep: str
    orb_off: str
    glow: float       # intensidad de los brillos (1 = neón)
    # Los dos últimos traen valor por defecto porque los temas oscuros ya los cumplían sin decirlo.
    dark: bool = True  # False en temas claros: el fondo de la ventana es claro
    hi: str = "#ffffff"  # el color de mayor contraste sobre las superficies del tema (tinta en los claros)


THEMES: dict[str, UITheme] = {
    "neon": UITheme(
        key="neon", name="Neón", description="Negro profundo con brillo azul",
        bg0="#03050b", bg1="#060a14", bg2="#08101f", bg3="#0c1628",
        line="#12203d", line_hi="#1b3363", input_bg="#050912", select_bg="#0f2a55",
        hover_bg="#0e1c36", press_bg="#0a1428",
        text="#e6f1ff", muted="#7d8bb0", dim="#4a5878", nav_hover="#cfe9ff", on_accent="#021018",
        accent="#00e5ff", ice="#7df9ff", blue="#2d7dff", indigo="#5b5bff", danger="#ff4d7a", ok="#3dffc5",
        primary_from="#2d7dff", primary_to="#00b8e6", primary_hover_from="#4a90ff", primary_hover_to="#00e5ff",
        keycap_bg="#0a1428", keycap_edge="#0b6f8c", titlebar_border="#0b6f8c",
        logo_idle="#0b1a38", logo_active="#0a2d52",
        orb_hi="#0d5d8f", orb_hi2="#07284d", orb_idle="#132f5a", orb_mid="#081327", orb_deep="#02050c",
        orb_off="#0c1426", glow=1.0,
    ),
    "glass": UITheme(
        key="glass", name="Cristal", description="Vidrio azul, claro y luminoso",
        bg0="#071227", bg1="#0b1b38", bg2="#102a52", bg3="#1a3c70",
        line="#24467e", line_hi="#37639f", input_bg="#0c1f3f", select_bg="#1d4380",
        hover_bg="#1b3f77", press_bg="#16345f",
        text="#f2fbff", muted="#a9c3e8", dim="#7192bd", nav_hover="#eaf4ff", on_accent="#04172e",
        accent="#7df9ff", ice="#ffffff", blue="#8fb4ff", indigo="#a99bff", danger="#ff7d9c", ok="#5ef0c0",
        primary_from="#8fb4ff", primary_to="#7df9ff", primary_hover_from="#a9c6ff", primary_hover_to="#b6fdff",
        keycap_bg="#14315f", keycap_edge="#5f8fd6", titlebar_border="#3a6cb0",
        logo_idle="#183a6d", logo_active="#2a68ab",
        orb_hi="#2f6fb5", orb_hi2="#17396e", orb_idle="#27538f", orb_mid="#122c55", orb_deep="#08182f",
        orb_off="#16294a", glow=0.8,
    ),
    "mono": UITheme(
        key="mono", name="Sutil", description="Negro con tonos blancos, sin color",
        bg0="#08080a", bg1="#0c0c0f", bg2="#111114", bg3="#1b1b20",
        line="#212126", line_hi="#33333a", input_bg="#0a0a0c", select_bg="#2a2a31",
        hover_bg="#232329", press_bg="#17171b",
        text="#f2f2f4", muted="#9a9aa4", dim="#6b6b75", nav_hover="#e6e6ea", on_accent="#0a0a0c",
        accent="#e8e8ec", ice="#ffffff", blue="#9a9aa4", indigo="#7a7a84", danger="#ff8a9e", ok="#ffffff",
        primary_from="#d4d4da", primary_to="#ffffff", primary_hover_from="#e8e8ee", primary_hover_to="#ffffff",
        keycap_bg="#17171c", keycap_edge="#5a5a63", titlebar_border="#3a3a42",
        logo_idle="#1c1c21", logo_active="#3a3a42",
        orb_hi="#4a4a52", orb_hi2="#232329", orb_idle="#2b2b31", orb_mid="#141418", orb_deep="#050506",
        orb_off="#131317", glow=0.55,
    ),
    "pastel": UITheme(
        key="pastel", name="Pastel", description="Crema con lavanda, menta y durazno",
        bg0="#f8f5f0", bg1="#f2eee7", bg2="#ffffff", bg3="#efeaf9",
        line="#e7e0d6", line_hi="#d5cbe6", input_bg="#ffffff", select_bg="#ddd2fb",
        hover_bg="#ece5fb", press_bg="#ddd3f6",
        text="#2e2544", muted="#6b5f86", dim="#6f6389", nav_hover="#3a2f5e", on_accent="#ffffff",
        accent="#6b4ef0", ice="#4a33b8", blue="#5b8def", indigo="#9a7bf5", danger="#c43c6a", ok="#0b7d60",
        primary_from="#6f4ae8", primary_to="#5a34d6", primary_hover_from="#5f3ada", primary_hover_to="#4c2bc0",
        keycap_bg="#f3eefd", keycap_edge="#b9a6ef", titlebar_border="#cabbef",
        logo_idle="#e7defd", logo_active="#cdbaff",
        orb_hi="#7c63e8", orb_hi2="#6247c9", orb_idle="#efe9ff", orb_mid="#e3d9ff", orb_deep="#d2c4f7",
        orb_off="#eceaf2", glow=0.35, dark=False, hi="#241b3f",
    ),
}
DEFAULT_THEME = "neon"
THEME = THEMES[DEFAULT_THEME]


# --- Paleta activa ------------------------------------------------------------
# set_theme() las reescribe; los widgets que pintan a mano las leen como T.CYAN, T.BG0, etc.
# (los colores que solo usa la hoja de estilos se leen del tema: THEME.input_bg, THEME.keycap_bg…)
BG0 = BG1 = BG2 = BG3 = LINE = LINE_HI = TEXT = MUTED = DIM = ON_ACCENT = HI = ""
CYAN = ICE = BLUE = INDIGO = DANGER = OK = ""
LOGO_IDLE = LOGO_ACTIVE = ORB_HI = ORB_HI2 = ORB_IDLE = ORB_MID = ORB_DEEP = ORB_OFF = ""
GLOW = 1.0

_ALIASES = {
    "BG0": "bg0", "BG1": "bg1", "BG2": "bg2", "BG3": "bg3", "LINE": "line", "LINE_HI": "line_hi",
    "TEXT": "text", "MUTED": "muted", "DIM": "dim", "ON_ACCENT": "on_accent", "HI": "hi",
    "CYAN": "accent", "ICE": "ice", "BLUE": "blue", "INDIGO": "indigo", "DANGER": "danger", "OK": "ok",
    "LOGO_IDLE": "logo_idle", "LOGO_ACTIVE": "logo_active",
    "ORB_HI": "orb_hi", "ORB_HI2": "orb_hi2", "ORB_IDLE": "orb_idle", "ORB_MID": "orb_mid",
    "ORB_DEEP": "orb_deep", "ORB_OFF": "orb_off", "GLOW": "glow",
}


def set_theme(key: str) -> UITheme:
    """Cambia la paleta activa. Después hay que volver a aplicar `build_stylesheet()` y repintar la ventana."""
    global THEME
    THEME = THEMES.get(key, THEMES[DEFAULT_THEME])
    globals().update({name: getattr(THEME, field) for name, field in _ALIASES.items()})
    return THEME


def qc(hex_color: str, alpha: float = 1.0) -> QColor:
    c = QColor(hex_color)
    c.setAlphaF(alpha)
    return c


def rgba(hex_color: str, alpha: float) -> str:
    """Color para la hoja de estilos: rgba(r, g, b, a)."""
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha:.3f})"


# --- Medidas y tipografías del diseño -----------------------------------------
# El aire, el redondeo y los tamaños viven aquí: cambiar un número repinta toda la app.
FONT_UI = '"Segoe UI Variable Text", "Segoe UI"'
FONT_DISPLAY = '"Century Gothic", "Trebuchet MS", "Segoe UI Variable Display"'
DISPLAY_FAMILIES = ["Century Gothic", "Trebuchet MS", "Segoe UI Variable Display", "Segoe UI"]

R_CARD = 20   # esquinas de las tarjetas
R_CTRL = 14   # botones, campos y listas
R_CHIP = 11   # etiquetas, teclas y píldoras
PAGE_MARGIN = 40      # margen de cada página
CARD_PAD = 24         # aire dentro de una tarjeta
BLOCK_GAP = 20        # separación entre tarjetas

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
    """Tipografía de los títulos y los números: redonda y con carácter."""
    f = QFont()
    f.setFamilies(DISPLAY_FAMILIES)  # la primera que exista en la PC
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
    PALETTE = ""
    THEME = ""
    MEETING = ""


# --- Hoja de estilos ----------------------------------------------------------
def build_stylesheet() -> str:
    """Hoja de estilos del tema activo. Se vuelve a aplicar al cambiar de tema."""
    t = THEME
    g = t.glow
    return f"""
* {{ outline: none; }}
QWidget {{ color: {t.text}; font-family: {FONT_UI}; font-size: 10.5pt; }}
QMainWindow, #Root {{ background: {t.bg0}; }}
#Sidebar {{ background: {t.bg1}; border-right: 1px solid {t.line}; }}
#Page, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
#Sep {{ background: {t.line}; }}

QLabel {{ background: transparent; }}
QLabel[role="h1"] {{ font-family: {FONT_DISPLAY}; font-size: 30pt; font-weight: 700; color: {t.text}; }}
QLabel[role="h2"] {{ font-family: {FONT_DISPLAY}; font-size: 15pt; font-weight: 700; color: {t.text}; }}
QLabel[role="eyebrow"] {{ font-size: 9pt; font-weight: 700; color: {t.accent}; letter-spacing: 1.8px; padding-top: 3px; }}
QLabel[role="mini"] {{ font-size: 8.5pt; font-weight: 700; color: {t.accent}; letter-spacing: 1.2px; padding-top: 3px; }}
QLabel[role="muted"] {{ color: {t.muted}; }}
QLabel[role="dim"] {{ color: {t.dim}; font-size: 9.5pt; }}
QLabel[role="stat"] {{ font-family: {FONT_DISPLAY}; font-size: 27pt; font-weight: 700; color: {t.ice}; }}
QLabel[role="icon"] {{ color: {t.accent}; }}
QLabel[role="title"] {{ font-size: 12pt; font-weight: 600; color: {t.text}; }}
QLabel[role="strong"] {{ font-weight: 600; color: {t.text}; }}
QLabel[role="body"] {{ color: {t.text}; font-size: 11.5pt; }}
QLabel[role="entry"] {{ color: {t.text}; font-size: 11pt; }}
QLabel[role="status"] {{ color: {t.ice}; }}
QLabel[role="pct"] {{ font-family: {FONT_DISPLAY}; font-size: 11pt; font-weight: 700; color: {t.ice}; }}
QLabel[role="badge"] {{
    color: {t.on_accent}; background: {t.accent}; border-radius: {R_CHIP}px; padding: 2px 10px;
    font-size: 8.5pt; font-weight: 700;
}}
QLabel[role="chip"] {{
    color: {t.muted}; background: {t.bg3}; border: 1px solid {t.line}; border-radius: {R_CHIP}px;
    padding: 3px 11px; font-size: 9pt; font-weight: 600;
}}
QLabel[role="chip"][tone="ok"] {{ color: {t.ok}; border-color: {rgba(t.ok, 0.45)}; background: {rgba(t.ok, 0.12)}; }}
QLabel[role="chip"][tone="danger"] {{ color: {t.danger}; border-color: {rgba(t.danger, 0.45)}; background: {rgba(t.danger, 0.12)}; }}
QLabel[role="chip"][tone="accent"] {{ color: {t.ice}; border-color: {rgba(t.accent, 0.45)}; background: {rgba(t.accent, 0.12)}; }}
QLabel[role="detail"] {{ font-size: 9.5pt; color: {t.muted}; }}
QLabel[role="micstatus"] {{ font-size: 10pt; color: {t.muted}; }}
QLabel[role="dlstatus"] {{ font-size: 9pt; color: {t.muted}; }}
QLabel[tone="ok"] {{ color: {t.ok}; }}
QLabel[tone="danger"] {{ color: {t.danger}; }}
QLabel[tone="accent"] {{ color: {t.ice}; }}
QLabel[tone="muted"] {{ color: {t.muted}; }}
QLabel#KeyCap {{
    background: {t.keycap_bg}; color: {t.ice}; border: 1px solid {rgba(t.accent, 0.45)};
    border-bottom: 3px solid {t.keycap_edge}; border-radius: {R_CHIP}px; padding: 4px 13px;
    font-family: {FONT_DISPLAY}; font-size: 11.5pt; font-weight: 700;
}}
QLabel#KeyPlus {{ color: {t.dim}; font-size: 11pt; }}

#Card {{ background: {t.bg2}; border: 1px solid {t.line}; border-radius: {R_CARD}px; }}
#Card[glow="true"] {{ border: 1px solid {rgba(t.accent, 0.30 * g + 0.10)}; }}
#Tile {{ background: {t.bg2}; border: 1px solid {t.line}; border-radius: {R_CARD}px; }}
#Tile:hover {{ border-color: {rgba(t.accent, 0.55)}; background: {t.hover_bg}; }}
#Row {{ background: transparent; border: 1px solid transparent; border-radius: {R_CTRL}px; }}
#Row:hover {{ background: {t.bg3}; border-color: {t.line}; }}

QPushButton {{
    background: {t.bg3}; border: 1px solid {t.line_hi}; border-radius: {R_CTRL}px;
    padding: 10px 18px; color: {t.text}; font-weight: 600;
}}
QPushButton:hover {{ border-color: {t.accent}; color: {t.ice}; background: {t.hover_bg}; }}
QPushButton:pressed {{ background: {t.press_bg}; }}
QPushButton:disabled {{ color: {t.dim}; border-color: {t.line}; }}
QPushButton[variant="primary"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {t.primary_from}, stop:1 {t.primary_to});
    border: 1px solid {rgba(t.ice, 0.55)}; color: {t.on_accent}; font-weight: 700;
}}
QPushButton[variant="primary"]:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {t.primary_hover_from}, stop:1 {t.primary_hover_to});
    color: {t.on_accent};
}}
QPushButton[variant="hero"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {t.primary_from}, stop:1 {t.primary_to});
    border: 1px solid {rgba(t.ice, 0.55)}; color: {t.on_accent}; font-family: {FONT_DISPLAY};
    font-size: 13pt; font-weight: 700; padding: 16px 22px; border-radius: {R_CARD}px;
}}
QPushButton[variant="hero"]:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {t.primary_hover_from}, stop:1 {t.primary_hover_to});
    color: {t.on_accent};
}}
QPushButton[variant="hero2"] {{
    background: {t.bg2}; border: 2px solid {rgba(t.accent, 0.40)}; color: {t.text};
    font-family: {FONT_DISPLAY}; font-size: 13pt; font-weight: 700; padding: 15px 22px;
    border-radius: {R_CARD}px;
}}
QPushButton[variant="hero2"]:hover {{ background: {t.hover_bg}; border-color: {t.accent}; color: {t.ice}; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; color: {t.muted}; padding: 8px 12px; }}
QPushButton[variant="ghost"]:hover {{ color: {t.ice}; background: {t.bg3}; border-color: {t.line_hi}; }}
QPushButton[variant="danger"]:hover {{ border-color: {t.danger}; color: {t.danger}; }}

QPushButton#NavButton {{
    text-align: left; padding: 13px 16px; border-radius: {R_CTRL}px; font-size: 11pt; font-weight: 600;
    color: {t.muted}; background: transparent; border: 1px solid transparent;
}}
QPushButton#NavButton:hover {{ background: {t.bg3}; color: {t.nav_hover}; }}
QPushButton#NavButton:checked {{
    color: {t.ice}; border: 1px solid {rgba(t.accent, 0.35)};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {rgba(t.accent, 0.16)}, stop:1 {rgba(t.blue, 0.03)});
}}

QPushButton#Segment {{ border-radius: 0; padding: 10px 18px; color: {t.muted}; background: {t.bg3}; font-weight: 600; }}
QPushButton#Segment:checked {{ color: {t.on_accent}; font-weight: 700; background: {t.accent}; border-color: {t.accent}; }}
QPushButton#Segment[pos="first"] {{ border-top-left-radius: {R_CTRL}px; border-bottom-left-radius: {R_CTRL}px; }}
QPushButton#Segment[pos="last"] {{ border-top-right-radius: {R_CTRL}px; border-bottom-right-radius: {R_CTRL}px; }}

QLineEdit, QPlainTextEdit {{
    background: {t.input_bg}; border: 1px solid {t.line_hi}; border-radius: {R_CTRL}px;
    padding: 10px 14px; selection-background-color: {t.select_bg}; color: {t.text};
}}
QLineEdit:focus, QPlainTextEdit:focus {{ border-color: {t.accent}; }}

QComboBox {{
    background: {t.input_bg}; border: 1px solid {t.line_hi}; border-radius: {R_CTRL}px;
    padding: 9px 14px; min-width: 240px; color: {t.text};
}}
QComboBox:hover, QComboBox:focus {{ border-color: {t.accent}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: none; width: 0; }}
QComboBox QAbstractItemView {{
    background: {t.bg2}; border: 1px solid {t.line_hi}; padding: 4px;
    selection-background-color: {t.select_bg}; selection-color: {t.ice}; outline: none;
}}

QSlider::groove:horizontal {{ height: 6px; background: {t.line_hi}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {t.blue}, stop:1 {t.accent}); border-radius: 3px; }}
QSlider::handle:horizontal {{ width: 18px; height: 18px; margin: -6px 0; border-radius: 9px; background: {t.ice}; border: 2px solid {t.accent}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {t.line_hi}; border-radius: 3px; min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: {rgba(t.accent, 0.5)}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}

QToolTip {{ background: {t.bg2}; color: {t.ice}; border: 1px solid {t.line_hi}; padding: 7px 10px; border-radius: 10px; }}
QMenu {{ background: {t.bg2}; border: 1px solid {t.line_hi}; padding: 6px; }}
QMenu::item {{ padding: 9px 22px; border-radius: 8px; color: {t.text}; }}
QMenu::item:selected {{ background: {t.select_bg}; color: {t.ice}; }}
QMenu::separator {{ height: 1px; background: {t.line}; margin: 6px 8px; }}
QMessageBox {{ background: {t.bg1}; }}
"""


def apply_titlebar(hwnd: int) -> None:
    """Barra de título con los colores del tema (Windows 11; en Windows 10 solo claro u oscuro)."""
    if sys.platform != "win32":
        return
    dwm = ctypes.windll.dwmapi

    def set_attr(attr: int, value: int) -> None:
        v = ctypes.c_int(value)
        dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v))

    def colorref(hex_color: str) -> int:
        c = QColor(hex_color)
        return c.red() | (c.green() << 8) | (c.blue() << 16)

    set_attr(20, 1 if THEME.dark else 0)       # DWMWA_USE_IMMERSIVE_DARK_MODE
    set_attr(35, colorref(THEME.bg1))          # DWMWA_CAPTION_COLOR
    set_attr(34, colorref(THEME.titlebar_border))  # DWMWA_BORDER_COLOR
    set_attr(36, colorref(THEME.ice))          # DWMWA_TEXT_COLOR


set_theme(DEFAULT_THEME)
