"""Quién está usando el audio de Windows ahora mismo, por proceso (WASAPI, vía COM).

Dos preguntas que responde este módulo:

* **¿Quién tiene el micrófono abierto?** (`capture_sessions`) — es la señal más fiable para saber que
  estás en una reunión: Zoom, Teams o Meet abren una sesión de captura en cuanto entras a la llamada.
* **¿Por qué salida está sonando?** (`render_sessions`) — cada app dice en qué endpoint reproduce, y
  el medidor dice si ese endpoint está sonando ahora. Sirve para grabar el loopback del dispositivo
  correcto y para seguirlo si la reunión cambia de salida (audífonos, HDMI…).

Ojo: el medidor de WASAPI que se obtiene de una sesión devuelve el nivel **del dispositivo**, no el de
esa app. Por eso no sirve para decidir «esta app está hablando», solo «esta salida está sonando».

Si algo falla con COM se devuelve una lista vacía: el detector tiene su propio plan B.
"""
import logging
import sys
from dataclasses import dataclass

log = logging.getLogger(__name__)

SPEAKING_PEAK = 0.002  # por encima de esto se considera que la app está reproduciendo audio


@dataclass(frozen=True)
class AudioSession:
    pid: int
    process: str       # "zoom.exe", en minúsculas
    peak: float        # nivel del DISPOSITIVO donde vive la sesión (0..1), no el de la app
    device_id: str     # id del endpoint de Windows
    device_name: str   # "Headset Earphone (HyperX…)"
    is_default: bool


def _process_names(pids: set[int]) -> dict[int, str]:
    """pid → nombre del ejecutable (y el de su padre, para árboles como Teams)."""
    names: dict[int, str] = {}
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return names
    for pid in pids:
        try:
            names[pid] = psutil.Process(pid).name().lower()
        except Exception:  # noqa: BLE001 - el proceso puede haber muerto
            continue
    return names


def parent_names(pid: int, depth: int = 3) -> list[str]:
    """Nombres del proceso y de sus padres: Teams reproduce audio desde procesos hijos."""
    out: list[str] = []
    try:
        import psutil

        proc = psutil.Process(pid)
        for _ in range(depth):
            out.append(proc.name().lower())
            proc = proc.parent()
            if proc is None:
                break
    except Exception:  # noqa: BLE001
        pass
    return out


def _sessions(capture: bool) -> list[AudioSession]:
    if sys.platform != "win32":
        return []
    try:
        from comtypes import CLSCTX_INPROC_SERVER, CoCreateInstance, POINTER, cast
        from pycaw.api.audiopolicy import IAudioSessionControl2, IAudioSessionManager2
        from pycaw.api.endpointvolume import IAudioMeterInformation
        from pycaw.api.mmdeviceapi import IMMDeviceEnumerator
        from pycaw.constants import CLSID_MMDeviceEnumerator, DEVICE_STATE, EDataFlow
    except Exception:  # noqa: BLE001
        log.exception("pycaw/comtypes no disponibles")
        return []

    flow = EDataFlow.eCapture.value if capture else EDataFlow.eRender.value
    found: list[AudioSession] = []
    try:
        enumerator = CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_INPROC_SERVER)
        try:
            default_id = enumerator.GetDefaultAudioEndpoint(flow, 0).GetId()
        except Exception:  # noqa: BLE001 - puede no haber dispositivo predeterminado
            default_id = ""
        devices = enumerator.EnumAudioEndpoints(flow, DEVICE_STATE.ACTIVE.value)
        raw: list[tuple[int, float, str, str]] = []
        for i in range(devices.GetCount()):
            device = devices.Item(i)
            device_id = device.GetId()
            try:
                name = device.OpenPropertyStore(0).GetValue(_DEVICE_NAME).GetValue()
            except Exception:  # noqa: BLE001
                name = ""
            try:
                manager = cast(
                    device.Activate(IAudioSessionManager2._iid_, CLSCTX_INPROC_SERVER, None),
                    POINTER(IAudioSessionManager2),
                )
                sessions = manager.GetSessionEnumerator()
            except Exception:  # noqa: BLE001
                continue
            for j in range(sessions.GetCount()):
                try:
                    control = sessions.GetSession(j).QueryInterface(IAudioSessionControl2)
                    if control.GetState() != 1:  # 1 = AudioSessionStateActive
                        continue
                    pid = control.GetProcessId()
                    peak = 0.0
                    try:
                        peak = control.QueryInterface(IAudioMeterInformation).GetPeakValue()
                    except Exception:  # noqa: BLE001
                        pass
                    raw.append((pid, peak, device_id, name))
                except Exception:  # noqa: BLE001
                    continue
        names = _process_names({pid for pid, *_ in raw})
        for pid, peak, device_id, name in raw:
            process = names.get(pid, "")
            if process:
                found.append(AudioSession(pid, process, peak, device_id, name, device_id == default_id))
    except Exception:  # noqa: BLE001
        log.exception("No se pudieron leer las sesiones de audio")
        return []
    return found


def capture_sessions() -> list[AudioSession]:
    """Apps con el micrófono abierto ahora mismo."""
    return _sessions(capture=True)


def render_sessions() -> list[AudioSession]:
    """Apps reproduciendo audio ahora mismo, con el dispositivo por el que suenan."""
    return _sessions(capture=False)


def loud_endpoints(min_peak: float = SPEAKING_PEAK) -> set[str]:
    """Ids de las salidas que están sonando ahora mismo."""
    return {s.device_id for s in render_sessions() if s.peak >= min_peak}


def output_device_for(pids: set[int], names: set[str] = frozenset()) -> AudioSession | None:
    """Por qué salida sale la reunión: la del proceso (o sus hijos) que esté sonando."""
    candidates = [
        s for s in render_sessions()
        if s.pid in pids or s.process in names or any(n in names for n in parent_names(s.pid))
    ]
    if not candidates:
        return None
    loud = [s for s in candidates if s.peak >= SPEAKING_PEAK]
    if loud:
        return max(loud, key=lambda s: s.peak)
    return next((s for s in candidates if s.is_default), None)


def _friendly_name_key():
    """PKEY_Device_FriendlyName: el nombre bonito del endpoint («Altavoces (Realtek)»)."""
    from ctypes import wintypes

    from comtypes import GUID
    from pycaw.api.mmdeviceapi.depend.structures import PROPERTYKEY

    key = PROPERTYKEY()
    key.fmtid = GUID("{A45C254E-DF1C-4EFD-8020-67D146A850E0}")
    key.pid = wintypes.DWORD(14)
    return key


try:
    _DEVICE_NAME = _friendly_name_key()
except Exception:  # noqa: BLE001 - sin pycaw no se leen nombres, pero el resto funciona
    _DEVICE_NAME = None
