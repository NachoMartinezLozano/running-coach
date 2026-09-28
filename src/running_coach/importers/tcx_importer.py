"""Importador de archivos TCX (algunas carreras del Amazfit Active 2 llegan en este formato)."""

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from running_coach.importers.common import (
    compute_km_splits,
    elevation_gain,
    file_hash,
    fill_distances,
    read_file_bytes,
    xml_local_name,
)
from running_coach.models import Activity, TrackPoint

# Valores del atributo Sport de TCX -> nombre canónico. Amazfit escribe "Run", no el estándar "Running".
SPORTS = {"running": "running", "run": "running", "biking": "cycling"}


def parse_tcx_file(path: Path, source: str = "bulk_export") -> Activity:
    """Punto de entrada: lee un .tcx o .tcx.gz del disco."""
    data = read_file_bytes(path)
    return parse_tcx(data, source=source, source_ref=file_hash(data))


def parse_tcx(data: bytes, *, source: str, source_ref: str) -> Activity:
    """Traduce un TCX a una Activity.

    Como en el FIT, preferimos el resumen del reloj (las vueltas) y usamos
    los puntos para lo que el resumen no trae.
    """
    # .strip(): algunos TCX traen espacios antes de la cabecera XML y el parser los rechaza
    root = ET.fromstring(data.strip())
    elements = list(root.iter())

    points = [p for p in (_trackpoint_to_point(e) for e in elements
                          if xml_local_name(e.tag) == "Trackpoint") if p is not None]
    if len(points) < 2:
        raise ValueError("El archivo no tiene suficientes puntos con hora")
    points.sort(key=lambda p: p.time)

    # Si el reloj no guardó la distancia en los puntos, la calculamos con el GPS
    if all(p.distance_m is None for p in points):
        fill_distances(points)

    laps = [e for e in elements if xml_local_name(e.tag) == "Lap"]
    lap_time = _sum_children(laps, "TotalTimeSeconds")
    lap_distance = _sum_children(laps, "DistanceMeters")
    point_distances = [p.distance_m for p in points if p.distance_m is not None]

    heart_rates = [p.heart_rate for p in points if p.heart_rate is not None]
    cadences = [p.cadence for p in points if p.cadence is not None]

    activity = Activity(
        source=source,
        source_ref=source_ref,
        start_time=points[0].time,
        distance_m=_first_not_none(lap_distance, max(point_distances, default=None), 0.0),
        duration_s=(points[-1].time - points[0].time).total_seconds(),
        sport=_sport(elements),
        device=_device(elements),
        moving_time_s=lap_time,  # TotalTimeSeconds es tiempo cronometrado (sin pausas)
        avg_hr=round(sum(heart_rates) / len(heart_rates), 1) if heart_rates else None,
        max_hr=max(heart_rates) if heart_rates else None,
        avg_cadence=round(sum(cadences) / len(cadences), 1) if cadences else None,
        elevation_gain_m=elevation_gain([p.altitude_m for p in points]),
    )
    activity.splits = compute_km_splits(points)
    return activity


def _trackpoint_to_point(element) -> TrackPoint | None:
    """Convierte un <Trackpoint> en un TrackPoint."""
    values = {xml_local_name(child.tag): child.text.strip()
              for child in element.iter()
              if child is not element and child.text and child.text.strip()}

    if "Time" not in values:
        return None

    heart_rate = _to_float(values.get("Value"))  # <HeartRateBpm><Value>...</Value></HeartRateBpm>
    cadence = _to_float(values.get("Cadence") or values.get("RunCadence"))
    return TrackPoint(
        time=_parse_time(values["Time"]),
        distance_m=_to_float(values.get("DistanceMeters")),
        lat=_to_float(values.get("LatitudeDegrees")),
        lon=_to_float(values.get("LongitudeDegrees")),
        altitude_m=_to_float(values.get("AltitudeMeters")),
        heart_rate=int(heart_rate) if heart_rate is not None else None,
        cadence=cadence * 2 if cadence is not None else None,  # zancadas/min -> pasos/min
    )


def _sum_children(laps, tag: str) -> float | None:
    """Suma un campo del resumen de todas las vueltas (solo hijos directos de <Lap>)."""
    values = [_to_float(child.text) for lap in laps for child in lap
              if xml_local_name(child.tag) == tag]
    values = [v for v in values if v is not None]
    return sum(values) if values else None


def _sport(elements) -> str:
    activity = next((e for e in elements if xml_local_name(e.tag) == "Activity"), None)
    raw = (activity.get("Sport") or "").strip().lower() if activity is not None else ""
    return SPORTS.get(raw, raw or "unknown")


def _device(elements) -> str | None:
    creator = next((e for e in elements if xml_local_name(e.tag) == "Creator"), None)
    if creator is None:
        return None
    name = next((e for e in creator.iter() if xml_local_name(e.tag) == "Name"), None)
    return name.text.strip() if name is not None and name.text else None


def _parse_time(text: str) -> datetime:
    dt = datetime.fromisoformat(text)
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _to_float(text: str | None) -> float | None:
    try:
        return float(text) if text is not None else None
    except ValueError:
        return None


def _first_not_none(*values):
    return next((v for v in values if v is not None), None)