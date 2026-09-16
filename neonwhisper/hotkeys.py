"""Atajo global de teclado (funciona aunque la app no tenga el foco)."""
import ctypes
import logging

import keyboard
from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)
_user32 = ctypes.windll.user32

MODIFIERS: dict[str, tuple[int, ...]] = {
    "ctrl": (0x11,),
    "alt": (0x12,),
    "shift": (0x10,),
    "windows": (0x5B, 0x5C),
}
_ALIASES = {
    "control": "ctrl", "left ctrl": "ctrl", "right ctrl": "ctrl", "ctrl derecha": "ctrl",
    "alt gr": "alt", "left alt": "alt", "right alt": "alt",
    "left shift": "shift", "right shift": "shift", "mayús": "shift", "mayus": "shift",
    "left windows": "windows", "right windows": "windows", "win": "windows",
    "escape": "esc",
}
_PRETTY = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "windows": "Win", "space": "Space", "esc": "Esc"}
_SAFE_SINGLE_KEYS = {f"f{i}" for i in range(1, 25)} | {"pause", "scroll lock", "insert"}


def normalize_key(name: str | None) -> str:
    n = (name or "").lower().strip()
    return _ALIASES.get(n, n)


def pretty_parts(hotkey: str) -> list[str]:
    return [_PRETTY.get(k, k.upper() if len(k) == 1 else k.title()) for k in hotkey.split("+") if k]


def is_safe_hotkey(hotkey: str) -> bool:
    """Evita atajos que se dispararían al escribir normal (p. ej. solo la letra «a»)."""
    parts = [normalize_key(p) for p in hotkey.split("+") if p]
    return any(p in MODIFIERS for p in parts) or (len(parts) == 1 and parts[0] in _SAFE_SINGLE_KEYS)


def modifiers_down() -> bool:
    return any(_user32.GetAsyncKeyState(vk) & 0x8000 for vks in MODIFIERS.values() for vk in vks)


def _vk_down(vk: int) -> bool:
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)


class HotkeyManager(QObject):
    pressed = Signal()
    released = Signal()
    escape_pressed = Signal()
    captured = Signal(str)
    capture_cancelled = Signal()

    def __init__(self):
        super().__init__()
        self._mods: set[str] = set()
        self._keys: list[set[int]] = []
        self._all_codes: set[int] = set()
        self._keys_down: set[int] = set()
        self._active = False
        self._capturing = False
        self._cap_mods: set[str] = set()
        self._cap_keys: list[str] = []
        self._cap_down: set[int] = set()
        self._hook = keyboard.hook(self._on_event)

    def set_hotkey(self, hotkey: str) -> None:
        parts = [normalize_key(p) for p in hotkey.split("+") if p]
        mods = {p for p in parts if p in MODIFIERS}
        keys = []
        for p in parts:
            if p in MODIFIERS:
                continue
            codes = set(keyboard.key_to_scan_codes(p, error_if_missing=False))
            if not codes:
                raise ValueError(f"Tecla desconocida: {p}")
            keys.append(codes)
        if not mods and not keys:
            raise ValueError("Atajo vacío")
        self._mods, self._keys = mods, keys
        self._all_codes = set().union(*keys) if keys else set()
        self._keys_down.clear()
        self._active = False
        log.info("Atajo registrado: %s", hotkey)

    def start_capture(self) -> None:
        self._cap_mods, self._cap_keys, self._cap_down = set(), [], set()
        self._capturing = True

    def cancel_capture(self) -> None:
        self._capturing = False

    def shutdown(self) -> None:
        try:
            keyboard.unhook(self._hook)
        except (KeyError, ValueError):
            pass

    # --- hilo del hook de teclado ---------------------------------------------
    def _on_event(self, e: keyboard.KeyboardEvent) -> None:
        try:
            name = normalize_key(e.name)
            down = e.event_type == keyboard.KEY_DOWN
            if self._capturing:
                self._capture_event(e.scan_code, name, down)
                return
            if name == "esc" and down:
                self.escape_pressed.emit()
            if e.scan_code in self._all_codes:
                (self._keys_down.add if down else self._keys_down.discard)(e.scan_code)
            matches = self._matches(e.scan_code, name, down)
            if matches and not self._active:
                self._active = True
                self.pressed.emit()
            elif not matches and self._active:
                self._active = False
                self.released.emit()
        except Exception:  # noqa: BLE001 - nunca romper el hook global
            log.exception("Error en el hook de teclado")

    def _matches(self, scan_code: int, name: str, down: bool) -> bool:
        if not self._mods and not self._keys:
            return False
        for mod, vks in MODIFIERS.items():
            is_down = down if name == mod else any(_vk_down(vk) for vk in vks)
            if (mod in self._mods) != is_down:
                return False
        for code in list(self._keys_down):
            if code == scan_code:
                continue
            vk = _user32.MapVirtualKeyW(code, 3)
            if vk and not _vk_down(vk):
                self._keys_down.discard(code)  # se perdió el evento de soltar
        return all(codes & self._keys_down for codes in self._keys)

    def _capture_event(self, scan_code: int, name: str, down: bool) -> None:
        if down:
            if name == "esc" and not self._cap_mods and not self._cap_keys:
                self._capturing = False
                self.capture_cancelled.emit()
                return
            self._cap_down.add(scan_code)
            if name in MODIFIERS:
                self._cap_mods.add(name)
            elif name and name not in self._cap_keys:
                self._cap_keys.append(name)
            return
        self._cap_down.discard(scan_code)
        if not self._cap_down and (self._cap_mods or self._cap_keys):
            ordered = [m for m in MODIFIERS if m in self._cap_mods]
            self._capturing = False
            self.captured.emit("+".join(ordered + self._cap_keys))
