"""Formatos legibles para tamaños, velocidades y tiempos."""


def fmt_bytes(n: float) -> str:
    if n >= 1e9:
        return f"{n / 1e9:.2f} GB"
    if n >= 1e6:
        return f"{n / 1e6:.0f} MB"
    return f"{n / 1e3:.0f} KB"


def fmt_speed(bps: float) -> str:
    return f"{bps / 1e6:.1f} MB/s" if bps >= 1e6 else f"{bps / 1e3:.0f} KB/s"


def fmt_eta(seconds: float | None) -> str:
    if seconds is None:
        return "calculando…"
    s = int(seconds)
    if s < 60:
        return f"faltan {s} s"
    if s < 3600:
        return f"faltan {s // 60} min {s % 60:02d} s"
    return f"faltan {s // 3600} h {(s % 3600) // 60:02d} min"
