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
    # Los últimos traen valor por defecto porque los temas oscuros ya los cumplían sin decirlo.
    dark: bool = True  # False en temas claros: el fondo de la ventana es claro
    hi: str = "#ffffff"  # el color de mayor contraste sobre las superficies del tema (tinta en los claros)
    rec: str = "#ff6a4d"  # grabando: su propio color, para no confundirlo con un error
    rec_ink: str = ""     # versión del anterior que sí se lee como texto ("" = el mismo)


THEMES: dict[str, UITheme] = {
    "neon": UITheme(
        key="neon", name="Neón", description="Negro profundo con brillo azul",
        bg0="#03050b", bg1="#060a14", bg2="#08101f", bg3="#0c1628",
        line="#12203d", line_hi="#1b3363", input_bg="#050912", select_bg="#0f2a55",
        hover_bg="#0e1c36", press_bg="#0a1428",
        text="#e6f1ff", muted="#7d8bb0", dim="#4a5878", nav_hover="#cfe9ff", on_accent="#021018",
        accent="#00e5ff", ice="#7df9ff", blue="#2d7dff", indigo="#5b5bff", danger="#ff4d7a", ok="#4ee6b4",
        primary_from="#2d7dff", primary_to="#2d7dff", primary_hover_from="#4a90ff", primary_hover_to="#4a90ff",
        keycap_bg="#0a1428", keycap_edge="#0b6f8c", titlebar_border="#0b6f8c",
        logo_idle="#0b1a38", logo_active="#0a2d52",
        orb_hi="#0d5d8f", orb_hi2="#07284d", orb_idle="#132f5a", orb_mid="#081327", orb_deep="#02050c",
        orb_off="#0c1426", glow=0.72, rec="#ff6a4d",
    ),
    "glass": UITheme(
        key="glass", name="Cristal", description="Vidrio azul, claro y luminoso",
        bg0="#071227", bg1="#0b1b38", bg2="#102a52", bg3="#1a3c70",
        line="#24467e", line_hi="#37639f", input_bg="#0c1f3f", select_bg="#1d4380",
        hover_bg="#1b3f77", press_bg="#16345f",
        text="#f2fbff", muted="#a9c3e8", dim="#7192bd", nav_hover="#eaf4ff", on_accent="#04172e",
        accent="#7df9ff", ice="#ffffff", blue="#8fb4ff", indigo="#a99bff", danger="#ff7d9c", ok="#6fefc4",
        primary_from="#8fb4ff", primary_to="#8fb4ff", primary_hover_from="#a9c6ff", primary_hover_to="#a9c6ff",
        keycap_bg="#14315f", keycap_edge="#5f8fd6", titlebar_border="#3a6cb0",
        logo_idle="#183a6d", logo_active="#2a68ab",
        orb_hi="#2f6fb5", orb_hi2="#17396e", orb_idle="#27538f", orb_mid="#122c55", orb_deep="#08182f",
        orb_off="#16294a", glow=0.60, rec="#ff8e6b",
    ),
    "mono": UITheme(
        key="mono", name="Sutil", description="Negro con tonos blancos, sin color",
        bg0="#08080a", bg1="#0c0c0f", bg2="#111114", bg3="#1b1b20",
        line="#212126", line_hi="#33333a", input_bg="#0a0a0c", select_bg="#2a2a31",
        hover_bg="#232329", press_bg="#17171b",
        text="#f2f2f4", muted="#9a9aa4", dim="#6b6b75", nav_hover="#e6e6ea", on_accent="#0a0a0c",
        accent="#e8e8ec", ice="#ffffff", blue="#9a9aa4", indigo="#7a7a84", danger="#ff9aab", ok="#9fd9c4",
        primary_from="#e4e4ea", primary_to="#e4e4ea", primary_hover_from="#f4f4f8", primary_hover_to="#f4f4f8",
        keycap_bg="#17171c", keycap_edge="#5a5a63", titlebar_border="#3a3a42",
        logo_idle="#1c1c21", logo_active="#3a3a42",
        orb_hi="#4a4a52", orb_hi2="#232329", orb_idle="#2b2b31", orb_mid="#141418", orb_deep="#050506",
        orb_off="#131317", glow=0.45, rec="#f08a6a",
    ),
    "pastel": UITheme(
        key="pastel", name="Pastel", description="Crema con lavanda, menta y durazno",
        # Los pasteles solo se usan como relleno: lo que es texto o trazo va en su versión profunda.
        bg0="#f8f4ee", bg1="#f1eae1", bg2="#fffcf8", bg3="#efe8df",
        line="#dfd4c3", line_hi="#d2c5b4", input_bg="#ffffff", select_bg="#dcd3f6",
        hover_bg="#ede6f9", press_bg="#dfd5f2",
        text="#2a2521", muted="#6e6459", dim="#847869", nav_hover="#1e1a16", on_accent="#ffffff",
        accent="#6b5bd2", ice="#4a3e9e", blue="#4069c6", indigo="#7a62d6", danger="#c0405f", ok="#17795b",
        primary_from="#6b5bd2", primary_to="#6b5bd2", primary_hover_from="#5b4bc2", primary_hover_to="#5b4bc2",
        keycap_bg="#f2ecfc", keycap_edge="#b6a6ea", titlebar_border="#dfd4c4",
        logo_idle="#efe9fb", logo_active="#ddd2f8",
        orb_hi="#fff0ea", orb_hi2="#fad3c4", orb_idle="#ffffff", orb_mid="#f0eafb", orb_deep="#e3d9f4",
        orb_off="#f1ede7", glow=0.30, dark=False, hi="#2e2570", rec="#e2604a", rec_ink="#bf4a33",
    ),
}
DEFAULT_THEME = "neon"
THEME = THEMES[DEFAULT_THEME]


# --- Paleta activa ------------------------------------------------------------
# set_theme() las reescribe; los widgets que pintan a mano las leen como T.CYAN, T.BG0, etc.
# (los colores que solo usa la hoja de estilos se leen del tema: THEME.input_bg, THEME.keycap_bg…)
BG0 = BG1 = BG2 = BG3 = LINE = LINE_HI = TEXT = MUTED = DIM = ON_ACCENT = HI = ""
CYAN = ICE = BLUE = INDIGO = DANGER = OK = REC = REC_INK = ""
LOGO_IDLE = LOGO_ACTIVE = ORB_HI = ORB_HI2 = ORB_IDLE = ORB_MID = ORB_DEEP = ORB_OFF = ""
GLOW = 1.0

_ALIASES = {
    "BG0": "bg0", "BG1": "bg1", "BG2": "bg2", "BG3": "bg3", "LINE": "line", "LINE_HI": "line_hi",
    "TEXT": "text", "MUTED": "muted", "DIM": "dim", "ON_ACCENT": "on_accent", "HI": "hi",
    "CYAN": "accent", "ICE": "ice", "BLUE": "blue", "INDIGO": "indigo", "DANGER": "danger", "OK": "ok",
    "REC": "rec",
    "LOGO_IDLE": "logo_idle", "LOGO_ACTIVE": "logo_active",
    "ORB_HI": "orb_hi", "ORB_HI2": "orb_hi2", "ORB_IDLE": "orb_idle", "ORB_MID": "orb_mid",
    "ORB_DEEP": "orb_deep", "ORB_OFF": "orb_off", "GLOW": "glow",
}


def set_theme(key: str) -> UITheme:
    """Cambia la paleta activa. Después hay que llamar a `apply_stylesheet()` y repintar la ventana."""
    global THEME
    THEME = THEMES.get(key, THEMES[DEFAULT_THEME])
    globals().update({name: getattr(THEME, field) for name, field in _ALIASES.items()})
    globals()["REC_INK"] = THEME.rec_ink or THEME.rec
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
FONT_DISPLAY = '"Segoe UI Variable Display", "Trebuchet MS", "Segoe UI"'
DISPLAY_FAMILIES = ["Segoe UI Variable Display", "Trebuchet MS", "Segoe UI"]

# Radios (px)
R_CARD = 18   # tarjetas
R_HERO = 22   # tarjeta principal del panel
R_CTRL = 12   # botones, campos, listas, nav y segmentos
R_CHIP = 11   # píldoras de estado (alto 22 / 2)
R_KEY = 10    # teclas del atajo
R_MENU = 14
R_ITEM = 8
R_TIP = 10

# Espaciados: todo múltiplo de 4
PAGE_MARGIN = 40      # margen lateral de cada página
PAGE_TOP = 32
PAGE_BOTTOM = 24
SECTION_GAP = 24      # entre secciones
CARD_GAP = 12         # entre tarjetas de una misma fila
CARD_PAD = 22         # aire dentro de una tarjeta
CONTENT_MAX = 1200    # el contenido no se estira más que esto en pantallas grandes

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
_hojas: dict[str, str] = {}   # una hoja ya armada por tema; se llena la primera vez que se pide


def build_stylesheet() -> str:
    """Hoja de estilos del tema activo, guardada para no volver a armarla en cada cambio.

    Si alguna vez se editan los colores de `THEMES` con la app corriendo, hay que llamar a
    `clear_stylesheet_cache()`; al arrancar de nuevo se arma sola.
    """
    hoja = _hojas.get(THEME.key)
    if hoja is None:
        hoja = _hojas[THEME.key] = _build_stylesheet()
    return hoja


def clear_stylesheet_cache() -> None:
    """Olvida las hojas guardadas: la siguiente vez se vuelven a armar con los colores de ahora."""
    _hojas.clear()


def apply_stylesheet(app) -> None:
    """Pone la hoja del tema activo en la app, por el camino corto.

    Reemplazar una hoja de estilos de `QApplication` que ya tiene contenido es lo más caro que
    hace Qt al cambiar de tema: vuelve a «polish» cada widget arrastrando los cachés viejos
    (≈720 ms en esta ventana). Vaciarla primero suelta el estilo intermedio, y volver a ponerla lo
    monta limpio: eso cuesta menos de la mitad (≈260 ms) y pinta exactamente igual.
    """
    hoja = build_stylesheet()
    app.setStyleSheet("")
    app.setStyleSheet(hoja)


def _build_stylesheet() -> str:
    t = THEME
    g = t.glow
    rec = t.rec_ink or t.rec  # como texto, el naranja de grabar necesita su versión profunda
    checked_bg = rgba(t.accent, 0.14)
    checked_edge = rgba(t.accent, 0.55)
    return f"""
* {{ outline: none; }}
QWidget {{ color: {t.text}; font-family: {FONT_UI}; font-size: 11pt; }}
QMainWindow, #Root {{ background: {t.bg0}; }}
#Sidebar {{ background: {t.bg1}; border-right: 1px solid {t.line}; }}
#Page, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
#Sep {{ background: {t.line}; }}

QLabel {{ background: transparent; }}
QLabel[role="h1"] {{ font-family: {FONT_DISPLAY}; font-size: 28pt; font-weight: 600; color: {t.text}; }}
QLabel[role="h2"] {{ font-family: {FONT_DISPLAY}; font-size: 15pt; font-weight: 600; color: {t.text}; }}
QLabel[role="eyebrow"] {{
    font-family: {FONT_DISPLAY}; font-size: 8.5pt; font-weight: 600; color: {t.accent};
    letter-spacing: 1.6px; padding-top: 3px;
}}
QLabel[role="mini"] {{
    font-family: {FONT_DISPLAY}; font-size: 8.5pt; font-weight: 600; color: {t.accent};
    letter-spacing: 1.2px; padding-top: 3px;
}}
QLabel[role="muted"] {{ color: {t.muted}; font-size: 9.5pt; }}
QLabel[role="dim"] {{ color: {t.dim}; font-size: 9.5pt; }}
QLabel[role="stat"] {{ font-family: {FONT_DISPLAY}; font-size: 22pt; font-weight: 600; color: {t.ice}; }}
QLabel[role="icon"] {{ color: {t.accent}; }}
QLabel[role="title"] {{ font-size: 12pt; font-weight: 600; color: {t.text}; }}
QLabel[role="strong"] {{ font-size: 12pt; font-weight: 600; color: {t.text}; }}
QLabel[role="body"] {{ color: {t.text}; font-size: 11pt; }}
QLabel[role="entry"] {{ color: {t.text}; font-size: 11pt; }}
/* El estado del orbe y la marca: la hoja de estilos pisa cualquier setFont(), así que van aquí. */
QLabel[role="status"] {{ font-family: {FONT_DISPLAY}; font-size: 15pt; font-weight: 600; color: {t.ice}; }}
QLabel#Brand {{ font-family: {FONT_DISPLAY}; font-size: 15pt; font-weight: 600; }}
QLabel[role="pct"] {{ font-size: 12pt; font-weight: 600; color: {t.ice}; }}
QLabel[role="badge"] {{
    color: {t.on_accent}; background: {t.accent}; border-radius: {R_CHIP}px; padding: 3px 10px;
    font-family: {FONT_DISPLAY}; font-size: 8.5pt; font-weight: 600;
}}
QLabel[role="chip"] {{
    color: {t.muted}; background: {t.bg3}; border: 1px solid {t.line}; border-radius: {R_CHIP}px;
    padding: 3px 10px; font-size: 9pt; font-weight: 600;
}}
QLabel[role="chip"][tone="ok"] {{ color: {t.ok}; border: 2px solid {rgba(t.ok, 0.45)}; background: {rgba(t.ok, 0.14)}; padding: 2px 9px; }}
QLabel[role="chip"][tone="danger"] {{ color: {t.danger}; border: 2px solid {rgba(t.danger, 0.45)}; background: {rgba(t.danger, 0.14)}; padding: 2px 9px; }}
QLabel[role="chip"][tone="accent"] {{ color: {t.ice}; border: 2px solid {rgba(t.accent, 0.45)}; background: {rgba(t.accent, 0.14)}; padding: 2px 9px; }}
QLabel[role="chip"][tone="rec"] {{ color: {rec}; border: 2px solid {rgba(t.rec, 0.55)}; background: {rgba(t.rec, 0.14)}; padding: 2px 9px; }}
QLabel[role="detail"] {{ font-size: 9.5pt; color: {t.muted}; }}
QLabel[role="micstatus"] {{ font-size: 9.5pt; color: {t.muted}; }}
QLabel[role="dlstatus"] {{ font-size: 9.5pt; color: {t.muted}; }}
QLabel[tone="ok"] {{ color: {t.ok}; }}
QLabel[tone="rec"] {{ color: {rec}; }}
QLabel[tone="danger"] {{ color: {t.danger}; }}
QLabel[tone="accent"] {{ color: {t.ice}; }}
QLabel[tone="muted"] {{ color: {t.muted}; }}
QLabel#KeyCap {{
    background: {t.keycap_bg}; color: {t.ice}; border: 1px solid {rgba(t.accent, 0.45)};
    border-bottom: 3px solid {t.keycap_edge}; border-radius: {R_KEY}px; padding: 5px 12px;
    font-family: {FONT_DISPLAY}; font-size: 11pt; font-weight: 600;
}}
QLabel#KeyPlus {{ color: {t.dim}; font-size: 11pt; }}

#Card {{ background: {t.bg2}; border: 1px solid {t.line}; border-radius: {R_CARD}px; }}
#Card[glow="true"] {{ border: 2px solid {rgba(t.accent, 0.35)}; }}
#Hero {{ background: {t.bg2}; border: 1px solid {t.line}; border-radius: {R_HERO}px; }}
#Tile {{ background: {t.bg2}; border: 1px solid {t.line}; border-radius: {R_CARD}px; }}
#Row {{ background: transparent; border: 1px solid transparent; border-radius: {R_CTRL}px; }}
#Row:hover {{ background: {t.bg3}; border-color: {t.line}; }}

QPushButton {{
    background: {t.bg3}; border: 1px solid {t.line_hi}; border-radius: {R_CTRL}px;
    padding: 9px 18px; color: {t.text}; font-weight: 600;
}}
QPushButton:hover {{ border-color: {t.accent}; color: {t.ice}; background: {t.hover_bg}; }}
QPushButton:pressed {{ background: {t.press_bg}; margin-top: 1px; }}
QPushButton:disabled {{ color: {t.dim}; border-color: {t.line}; }}
QPushButton[variant="primary"] {{
    background: {t.primary_from}; border: 1px solid {t.primary_from}; color: {t.on_accent};
    font-weight: 600; padding: 11px 22px;
}}
QPushButton[variant="primary"]:hover {{
    background: {t.primary_hover_from}; border-color: {t.primary_hover_from}; color: {t.on_accent};
}}
/* Apagado, un botón primario tiene que dejar de parecer picable: sin relleno y con la tinta floja. */
QPushButton[variant="primary"]:disabled, QPushButton[variant="hero"]:disabled {{
    background: {t.bg3}; border-color: {t.line}; color: {t.dim};
}}
QPushButton[variant="hero"] {{
    background: {t.primary_from}; border: 1px solid {t.primary_from}; color: {t.on_accent};
    font-family: {FONT_DISPLAY}; font-size: 13pt; font-weight: 600; padding: 14px 22px;
    border-radius: {R_CTRL + 2}px;
}}
QPushButton[variant="hero"]:hover {{ background: {t.primary_hover_from}; border-color: {t.primary_hover_from}; }}
QPushButton[variant="hero2"] {{
    background: {t.bg2}; border: 2px solid {rgba(t.accent, 0.45)}; color: {t.text};
    font-family: {FONT_DISPLAY}; font-size: 13pt; font-weight: 600; padding: 13px 21px;
    border-radius: {R_CTRL + 2}px;
}}
QPushButton[variant="hero2"]:hover {{ background: {t.hover_bg}; border-color: {t.accent}; color: {t.ice}; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; color: {t.muted}; padding: 6px 12px; }}
QPushButton[variant="ghost"]:hover {{ color: {t.ice}; background: {t.bg3}; border-color: {t.line_hi}; }}
QPushButton[variant="ghost"]:pressed {{ color: {t.ice}; background: {t.press_bg}; border-color: {t.line_hi}; }}
QPushButton[variant="danger"]:hover {{ border-color: {t.danger}; color: {t.danger}; }}
QPushButton::menu-indicator {{ image: none; width: 0; }}

QPushButton#NavButton {{
    text-align: left; padding: 12px 16px; border-radius: {R_CTRL}px; font-size: 11pt; font-weight: 600;
    color: {t.muted}; background: transparent; border: 1px solid transparent;
}}
QPushButton#NavButton:hover {{ background: {t.bg3}; color: {t.nav_hover}; }}
QPushButton#NavButton:pressed {{ background: {t.press_bg}; color: {t.nav_hover}; }}
QPushButton#NavButton:checked {{
    color: {t.ice}; border: 2px solid {checked_edge}; background: {checked_bg}; padding: 11px 15px;
}}

QPushButton#Segment {{ border-radius: 0; padding: 8px 18px; color: {t.muted}; background: {t.bg3}; font-weight: 600; }}
QPushButton#Segment:hover {{ color: {t.nav_hover}; background: {t.hover_bg}; }}
QPushButton#Segment:pressed {{ background: {t.press_bg}; }}
QPushButton#Segment:checked {{ color: {t.on_accent}; background: {t.accent}; border-color: {t.accent}; }}
QPushButton#Segment:checked:hover {{ color: {t.on_accent}; background: {t.primary_hover_from}; }}
QPushButton#Segment[pos="first"] {{ border-top-left-radius: {R_CTRL}px; border-bottom-left-radius: {R_CTRL}px; }}
QPushButton#Segment[pos="last"] {{ border-top-right-radius: {R_CTRL}px; border-bottom-right-radius: {R_CTRL}px; }}

QLineEdit, QPlainTextEdit {{
    background: {t.input_bg}; border: 1px solid {t.line_hi}; border-radius: {R_CTRL}px;
    padding: 9px 14px; selection-background-color: {t.select_bg}; color: {t.text};
}}
QLineEdit:focus, QPlainTextEdit:focus {{ border: 2px solid {t.accent}; padding: 8px 13px; }}

QComboBox {{
    background: {t.input_bg}; border: 1px solid {t.line_hi}; border-radius: {R_CTRL}px;
    padding: 9px 14px; min-width: 240px; color: {t.text};
}}
QComboBox:hover {{ border-color: {t.accent}; }}
QComboBox:focus {{ border: 2px solid {t.accent}; padding: 8px 13px; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: none; width: 0; }}
QComboBox QAbstractItemView {{
    background: {t.bg2}; border: 1px solid {t.line_hi}; padding: 4px; border-radius: {R_MENU}px;
    selection-background-color: {t.select_bg}; selection-color: {t.ice}; outline: none;
}}

QCheckBox {{ spacing: 10px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 6px; background: {t.input_bg}; border: 1px solid {t.line_hi};
}}
QCheckBox::indicator:hover {{ border-color: {t.accent}; }}
QCheckBox::indicator:checked {{ background: {t.accent}; border-color: {t.accent}; }}
QCheckBox:disabled {{ color: {t.dim}; }}
QCheckBox::indicator:disabled {{ background: {t.bg3}; border-color: {t.line}; }}
QCheckBox::indicator:checked:disabled {{ background: {t.dim}; border-color: {t.dim}; }}

QSlider::groove:horizontal {{ height: 6px; background: {t.line_hi}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 3px; }}
QSlider::handle:horizontal {{ width: 18px; height: 18px; margin: -6px 0; border-radius: 9px; background: {t.bg2}; border: 2px solid {t.accent}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {t.line_hi}; border-radius: 5px; min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: {rgba(t.accent, 0.5)}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}

QToolTip {{ background: {t.bg2}; color: {t.ice}; border: 1px solid {t.line_hi}; padding: 7px 10px; border-radius: {R_TIP}px; }}
QMenu {{ background: {t.bg2}; border: 1px solid {t.line_hi}; padding: 6px; border-radius: {R_MENU}px; }}
QMenu::item {{ padding: 9px 22px; border-radius: {R_ITEM}px; color: {t.text}; }}
QMenu::item:selected {{ background: {t.select_bg}; color: {t.ice}; }}
QMenu::separator {{ height: 1px; background: {t.line}; margin: 6px 8px; }}
QMessageBox {{ background: {t.bg1}; }}
"""


def apply_titlebar(hwnd: int) -> None:
    """Barra de título con los colores del tema (Windows 11; en Windows 10 solo claro u oscuro).

    Con `hwnd` en 0 no hay nada que pintar: pasa cuando la ventana todavía no tiene su hueco
    nativo. Se sale sin hacer ruido en vez de llamar a Windows con un identificador que no vale.
    """
    if sys.platform != "win32" or not hwnd:
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
