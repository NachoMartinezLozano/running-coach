"""Importador de archivos GPX (carreras grabadas con la app de Strava en el móvil)."""

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from running_coach.importers.common import (
    compute_km_splits,
    elevation_gain,
    file_hash,
    fill_distances,
    moving_time_series,
    read_file_bytes,
    xml_local_name,
)
from running_coach.models import Activity, TrackPoint


def parse_gpx_file(path: Path, source: str = "bulk_export") -> Activity:
    """Punto de entrada: lee un .gpx o .gpx.gz del disco."""
    data = read_file_bytes(path)
    return parse_gpx(data, source=source, source_ref=file_hash(data))


def parse_gpx(data: bytes, *, source: str, source_ref: str) -> Activity:
    """Traduce un GPX a una Activity. Como no trae resumen, todo se calcula a partir de los puntos."""
    root = ET.fromstring(data)

    points = []
    for element in root.iter():
        if xml_local_name(element.tag) == "trkpt":
            point = _trkpt_to_point(element)
            if point is not None:
                points.append(point)

    if len(points) < 2:
        raise ValueError("El archivo no tiene suficientes puntos con hora")

    points.sort(key=lambda p: p.time)  # por si los segmentos vinieran desordenados
    fill_distances(points)
    heart_rates = [p.heart_rate for p in points if p.heart_rate is not None]
    cadences = [p.cadence for p in points if p.cadence is not None]

    activity = Activity(
        source=source,
        source_ref=source_ref,
        start_time=points[0].time,
        distance_m=points[-1].distance_m,
        duration_s=(points[-1].time - points[0].time).total_seconds(),
        sport=_sport(root),
        device=_device(root),
        moving_time_s=moving_time_series(points)[-1],
        avg_hr=round(sum(heart_rates) / len(heart_rates), 1) if heart_rates else None,
        max_hr=max(heart_rates) if heart_rates else None,
        avg_cadence=round(sum(cadences) / len(cadences), 1) if cadences else None,
        elevation_gain_m=elevation_gain([p.altitude_m for p in points]),
    )
    activity.splits = compute_km_splits(points)
    return activity


def _trkpt_to_point(element) -> TrackPoint | None:
    """Convierte un <trkpt> en un TrackPoint."""
    # Recogemos el texto de todas las etiquetas del punto, incluidas las anidadas en <extensions>
    values = {xml_local_name(child.tag): child.text.strip()
              for child in element.iter()
              if child is not element and child.text and child.text.strip()}

    if "time" not in values:
        return None  # un punto sin hora no nos sirve

    cadence = _to_float(values.get("cad"))
    heart_rate = _to_float(values.get("hr"))
    return TrackPoint(
        time=_parse_time(values["time"]),
        lat=_to_float(element.get("lat")),
        lon=_to_float(element.get("lon")),
        altitude_m=_to_float(values.get("ele")),
        heart_rate=int(heart_rate) if heart_rate is not None else None,
        cadence=cadence * 2 if cadence is not None else None,  # zancadas/min -> pasos/min
    )


def _sport(root) -> str:
    text = next((el.text for el in root.iter() if xml_local_name(el.tag) == "type" and el.text), None)
    return text.strip().lower() if text else "unknown"


def _device(root) -> str | None:
    creator = root.get("creator")
    if creator and creator.startswith("StravaGPX"):
        return "Strava (app móvil)"
    return creator


def _parse_time(text: str) -> datetime:
    dt = datetime.fromisoformat(text)  # entiende el formato ISO 8601, incluida la 'Z' de UTC
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _to_float(text: str | None) -> float | None:
    try:
        return float(text) if text is not None else None
    except ValueError:
        return None