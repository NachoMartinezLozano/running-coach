"""Importador de archivos FIT (formato nativo del Amazfit Active 2)."""

import io
from datetime import timezone
from pathlib import Path

import fitdecode

from running_coach.importers.common import file_hash, read_file_bytes
from running_coach.models import Activity, TrackPoint

# El formato FIT guarda las coordenadas en "semicírculos" (enteros de 32 bits)
SEMICIRCLES_TO_DEGREES = 180 / 2**31


def parse_fit_file(path: Path, source: str = "bulk_export") -> tuple[Activity, list[TrackPoint]]:
    """Punto de entrada: lee un .fit o .fit.gz del disco."""
    data = read_file_bytes(path)
    return parse_fit(data, source=source, source_ref=file_hash(data))


def parse_fit(data: bytes, *, source: str, source_ref: str) -> tuple[Activity, list[TrackPoint]]:
    """Traduce el contenido de un archivo FIT a una Activity y su lista de puntos."""
    session = None
    points: list[TrackPoint] = []

    with fitdecode.FitReader(io.BytesIO(data)) as fit:
        for frame in fit:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue  # ignoramos los mensajes de definición
            if frame.name == "record":
                point = _record_to_point(frame)
                if point is not None:
                    points.append(point)
            elif frame.name == "session" and session is None:
                session = frame  # nos quedamos con la primera sesión

    if session is None and not points:
        raise ValueError("El archivo no contiene ni resumen ni registros")

    activity = _build_activity(session, points, source=source, source_ref=source_ref)
    return activity, points


def _build_activity(session, points: list[TrackPoint], *, source: str, source_ref: str) -> Activity:
    """Usa el resumen del reloj y, si falta algún dato, lo calcula a partir de los puntos."""
    first, last = (points[0], points[-1]) if points else (None, None)

    start_time = _first_not_none(
        _value(session, "start_time"),
        first.time if first else None,
    )
    distance = _first_not_none(
        _value(session, "total_distance"),
        last.distance_m if last else None,
        0.0,  # sesiones sin distancia, como las de pesas
    )
    duration = _first_not_none(
        _value(session, "total_elapsed_time"),
        (last.time - first.time).total_seconds() if first else None,
    )

    return Activity(
        source=source,
        source_ref=source_ref,
        start_time=_as_utc(start_time),
        distance_m=float(distance),
        duration_s=float(duration),
        sport=_value(session, "sport") or "unknown",
        moving_time_s=_value(session, "total_timer_time"),
        avg_hr=_value(session, "avg_heart_rate"),
        max_hr=_value(session, "max_heart_rate"),
        avg_cadence=_session_cadence(session),
        elevation_gain_m=_value(session, "total_ascent"),
    )


def _record_to_point(frame) -> TrackPoint | None:
    """Convierte un mensaje 'record' en un TrackPoint."""
    time = _value(frame, "timestamp")
    if time is None:
        return None  # un punto sin hora no nos sirve para nada

    lat, lon = _value(frame, "position_lat"), _value(frame, "position_long")
    cadence = _first_not_none(_value(frame, "cadence256"), _value(frame, "cadence"))

    return TrackPoint(
        time=_as_utc(time),
        distance_m=_value(frame, "distance"),
        lat=lat * SEMICIRCLES_TO_DEGREES if lat is not None else None,
        lon=lon * SEMICIRCLES_TO_DEGREES if lon is not None else None,
        altitude_m=_first_not_none(_value(frame, "enhanced_altitude"), _value(frame, "altitude")),
        heart_rate=_value(frame, "heart_rate"),
        cadence=cadence * 2 if cadence is not None else None,  # zancadas/min -> pasos/min
    )


def _session_cadence(session) -> float | None:
    """Cadencia media en pasos/min: (parte entera + decimales) × 2 piernas."""
    strides = _value(session, "avg_running_cadence")
    if strides is None:
        return None
    fraction = _value(session, "avg_fractional_cadence") or 0
    return round((strides + fraction) * 2, 1)


def _value(frame, name: str):
    """Lee un campo de un mensaje. Devuelve None si no existe, en vez de lanzar un error."""
    if frame is None:
        return None
    try:
        return frame.get_value(name, fallback=None)
    except Exception:  # algunos dispositivos escriben campos con definiciones corruptas
        return None


def _first_not_none(*values):
    """Devuelve el primer valor que no sea None."""
    return next((v for v in values if v is not None), None)


def _as_utc(dt):
    """Garantiza que la fecha lleva zona horaria UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)