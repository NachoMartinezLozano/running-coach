"""Lectura del activities.csv de la exportación de Strava.

Resuelve tres problemas del archivo:
- Los nombres de las columnas dependen del idioma de la cuenta de Strava.
- Algunas columnas aparecen dos veces con el mismo nombre: la primera con el
  valor formateado y la última con el valor bruto (metros, segundos). Usamos la última.
- Los números pueden venir vacíos o con coma decimal.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

# Campo canónico -> nombres conocidos de la columna (español, inglés)
COLUMN_ALIASES = {
    "activity_id": ("ID de actividad", "Activity ID"),
    "name": ("Nombre de la actividad", "Activity Name"),
    "type": ("Tipo de actividad", "Activity Type"),
    "description": ("Descripción de la actividad", "Activity Description"),
    "private_note": ("Nota privada de actividad", "Activity Private Note"),
    "filename": ("Nombre del archivo", "Filename"),
    "distance": ("Distancia", "Distance"),
    "elapsed_time": ("Tiempo transcurrido", "Elapsed Time"),
    "moving_time": ("Tiempo en movimiento", "Moving Time"),
    "elevation_gain": ("Desnivel positivo", "Elevation Gain"),
    "perceived_exertion": ("Esfuerzo Percibido", "Perceived Exertion"),
}

# Sin estas columnas el CSV no nos sirve
REQUIRED_FIELDS = ("activity_id", "type", "filename", "distance", "moving_time")

# Tipo de actividad de Strava (en cualquier idioma soportado) -> nombre canónico
ACTIVITY_TYPES = {
    "carrera": "running", "run": "running",
    "caminata": "walking", "walk": "walking",
    "bicicleta": "cycling", "ride": "cycling",
    "senderismo": "hiking", "hike": "hiking",
    "entrenamiento con pesas": "strength", "weight training": "strength",
    "entrenamiento": "workout", "workout": "workout",
}


@dataclass
class StravaCsvRecord:
    """Una fila del CSV, ya limpia y con nombres independientes del idioma."""

    activity_id: str
    sport: str
    filename: str | None  # p. ej. "activities/13258028954.gpx"
    name: str | None
    notes: str | None  # descripción y nota privada, juntas
    distance_m: float | None
    elapsed_time_s: float | None
    moving_time_s: float | None
    elevation_gain_m: float | None
    perceived_exertion: int | None  # 1-10, si se anotó en Strava


def read_activities_csv(path: Path) -> list[StravaCsvRecord]:
    """Lee el activities.csv y devuelve una lista de registros."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        columns = _locate_columns(header)
        return [_row_to_record(row, columns) for row in reader if row]


def _locate_columns(header: list[str]) -> dict[str, int]:
    """Averigua en qué posición está cada campo, sea cual sea el idioma."""
    columns = {}
    for field, aliases in COLUMN_ALIASES.items():
        positions = [i for i, name in enumerate(header) if name.strip() in aliases]
        if positions:
            columns[field] = positions[-1]  # si está repetida, la última: el valor bruto
    missing = [field for field in REQUIRED_FIELDS if field not in columns]
    if missing:
        raise ValueError(f"Faltan columnas en el CSV: {missing}. "
                         "¿Está la cuenta de Strava en un idioma no soportado?")
    return columns


def _row_to_record(row: list[str], columns: dict[str, int]) -> StravaCsvRecord:
    def text(field: str) -> str | None:
        position = columns.get(field)
        if position is None or position >= len(row):
            return None
        value = row[position].replace("\r\n", "\n").replace("\r", "\n").strip()
        return value or None  # las celdas vacías pasan a None

    raw_type = (text("type") or "").lower()
    notes = "\n".join(t for t in (text("description"), text("private_note")) if t)
    exertion = _to_number(text("perceived_exertion"))

    return StravaCsvRecord(
        activity_id=text("activity_id"),
        sport=ACTIVITY_TYPES.get(raw_type, raw_type or "unknown"),
        filename=text("filename"),
        name=text("name"),
        notes=notes or None,
        distance_m=_to_number(text("distance")),
        elapsed_time_s=_to_number(text("elapsed_time")),
        moving_time_s=_to_number(text("moving_time")),
        elevation_gain_m=_to_number(text("elevation_gain")),
        perceived_exertion=int(exertion) if exertion is not None else None,
    )


def _to_number(text: str | None) -> float | None:
    """Convierte '4030.5', '4,03' o None en número."""
    if text is None:
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")  # coma decimal
    try:
        return float(text)
    except ValueError:
        return None