"""Diseños de la barra flotante y cómo se pinta la píldora (se usa en la barra real y en las vistas previas)."""
from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QLinearGradient, QPainter, QPainterPath, QPen

from neonwhisper.ui import theme as T

# Los diseños de la barra no dependen del tema de la app: cada uno tiene su propia paleta fija.
N = T.THEMES["neon"]
P = T.THEMES["pastel"]


@dataclass(frozen=True)
class OverlayStyle:
    key: str
    name: str
    description: str
    width: int                      # tamaño de la píldora al 100 %
    height: int
    bg_top: str
    bg_bottom: str
    bg_alpha: float                 # opacidad propia del diseño; el ajuste «Fondo» la multiplica
    accents: dict[str, str]         # recording | processing | ok | error
    text: dict[str, str]
    bars: tuple[tuple[float, str], ...]
    bar_width: float
    bar_gap: float
    halo: float                     # intensidad del brillo exterior (0 = sin brillo)
    halo_color: str | None          # None = color del estado
    edge: str                       # color del borde en los extremos
    edge_alpha: float
    border_accent: float            # opacidad del color del estado en el centro del borde
    border_width: float
    sheen: float                    # reflejo de cristal en la mitad superior
    font_size: float
    font_weight: QFont.Weight
    icon: str
    icon_hover: str
    hover_bg: str


STYLES: dict[str, OverlayStyle] = {
    "neon": OverlayStyle(
        "neon", "Neón", "Negro profundo con brillo azul", 440, 64,
        bg_top="#081022", bg_bottom="#03050b", bg_alpha=1.0,
        accents={"recording": N.accent, "processing": N.blue, "ok": N.ok, "error": N.danger},
        text={"recording": N.ice, "processing": N.ice, "ok": N.ok, "error": N.danger},
        bars=((0, N.blue), (0.6, N.accent), (1, N.ice)), bar_width=4, bar_gap=3,
        halo=0.10, halo_color=None, edge=N.blue, edge_alpha=0.7, border_accent=0.95, border_width=1.4,
        sheen=0.0, font_size=11, font_weight=QFont.Weight.DemiBold,
        icon=N.muted, icon_hover=N.ice, hover_bg="rgba(0,229,255,0.14)",
    ),
    "glass": OverlayStyle(
        "glass", "Cristal", "Vidrio azul translúcido", 440, 64,
        bg_top="#21406f", bg_bottom="#0a1733", bg_alpha=0.72,
        accents={"recording": N.ice, "processing": "#8fb4ff", "ok": N.ok, "error": "#ff7d9c"},
        text={"recording": "#f2fbff", "processing": "#dce8ff", "ok": N.ok, "error": "#ff7d9c"},
        bars=((0, "#8fb4ff"), (0.55, N.ice), (1, "#ffffff")), bar_width=4, bar_gap=3,
        halo=0.06, halo_color="#7fb2ff", edge="#ffffff", edge_alpha=0.22, border_accent=0.6, border_width=1.2,
        sheen=0.16, font_size=11, font_weight=QFont.Weight.DemiBold,
        icon="#a9c3e8", icon_hover="#ffffff", hover_bg="rgba(255,255,255,0.14)",
    ),
    "mono": OverlayStyle(
        "mono", "Sutil", "Negro con tonos blancos, ligera", 400, 52,
        bg_top="#141416", bg_bottom="#08080a", bg_alpha=0.88,
        accents={"recording": "#ffffff", "processing": "#b8b8b8", "ok": "#ffffff", "error": "#ff8a9e"},
        text={"recording": "#f5f5f5", "processing": "#d0d0d0", "ok": "#ffffff", "error": "#ff8a9e"},
        bars=((0, "#7a7a7a"), (1, "#ffffff")), bar_width=3, bar_gap=3,
        halo=0.07, halo_color="#000000", edge="#ffffff", edge_alpha=0.16, border_accent=0.0, border_width=1.0,
        sheen=0.0, font_size=10, font_weight=QFont.Weight.Normal,
        icon="#8c8c8c", icon_hover="#ffffff", hover_bg="rgba(255,255,255,0.10)",
    ),
    "pastel": OverlayStyle(
        "pastel", "Pastel", "Crema clarita con lavanda", 440, 64,
        bg_top="#ffffff", bg_bottom="#f1ebff", bg_alpha=0.97,
        accents={"recording": P.accent, "processing": P.blue, "ok": P.ok, "error": P.danger},
        text={"recording": P.ice, "processing": P.ice, "ok": P.ok, "error": P.danger},
        bars=((0, P.indigo), (0.6, P.accent), (1, P.ice)), bar_width=4.5, bar_gap=3.5,
        halo=0.09, halo_color=P.accent, edge=P.line_hi, edge_alpha=0.95, border_accent=0.45, border_width=1.4,
        sheen=0.0, font_size=11, font_weight=QFont.Weight.DemiBold,
        icon=P.muted, icon_hover=P.ice, hover_bg="rgba(107,78,240,0.14)",
    ),
}
DEFAULT_STYLE = "neon"


def get_style(key: str) -> OverlayStyle:
    return STYLES.get(key, STYLES[DEFAULT_STYLE])


def paint_pill(p: QPainter, pill: QRectF, look: OverlayStyle, state: str, bg_opacity: float, halo_size: float) -> None:
    accent = look.accents[state]
    radius = pill.height() / 2

    if look.halo and halo_size >= 2:  # brillo exterior
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(int(halo_size), 0, -2):
            alpha = look.halo * (1 - i / halo_size) ** 2
            p.setPen(QPen(T.qc(look.halo_color or accent, alpha), 2))
            p.drawRoundedRect(pill.adjusted(-i, -i, i, i), radius + i, radius + i)

    path = QPainterPath()
    path.addRoundedRect(pill, radius, radius)
    alpha = look.bg_alpha * bg_opacity
    bg = QLinearGradient(pill.topLeft(), pill.bottomLeft())
    bg.setColorAt(0, T.qc(look.bg_top, alpha))
    bg.setColorAt(1, T.qc(look.bg_bottom, alpha))
    p.fillPath(path, bg)

    if look.sheen:
        strength = look.sheen * (0.35 + 0.65 * bg_opacity)
        gloss = QLinearGradient(pill.topLeft(), pill.bottomLeft())
        gloss.setColorAt(0, T.qc("#ffffff", strength))
        gloss.setColorAt(0.48, T.qc("#ffffff", strength * 0.2))
        gloss.setColorAt(0.5, T.qc("#ffffff", 0))
        p.fillPath(path, gloss)

    border = QLinearGradient(pill.topLeft(), pill.topRight())
    border.setColorAt(0, T.qc(look.edge, look.edge_alpha))
    border.setColorAt(0.5, T.qc(accent, look.border_accent) if look.border_accent else T.qc(look.edge, look.edge_alpha))
    border.setColorAt(1, T.qc(look.edge, look.edge_alpha))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(border, look.border_width))
    p.drawPath(path)
