"""Compara lo que calcula nuestro importador de GPX con lo que calculó Strava.

Uso: uv run python scripts/compare_gpx_with_strava.py [año_mínimo]   (por defecto, 2025)
"""

import csv
import re
import sys
from pathlib import Path
from statistics import mean

from running_coach.importers.gpx_importer import parse_gpx_file

EXPORT_DIR = Path("data/strava_export")
MIN_YEAR = int(sys.argv[1]) if len(sys.argv) > 1 else 2025


def last_index(header: list[str], name: str) -> int:
    """Posición de la ÚLTIMA columna con ese nombre (el bloque de valores brutos)."""
    return max(i for i, col in enumerate(header) if col == name)


def to_number(text: str) -> float | None:
    """Convierte '4069.1', '4,07' o '' en número."""
    text = text.strip()
    if not text:
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")  # coma decimal
    return float(text)


with open(EXPORT_DIR / "activities.csv", encoding="utf-8-sig", newline="") as f:
    reader = csv.reader(f)
    header = next(reader)
    rows = list(reader)

col_date = header.index("Fecha de la actividad")
col_type = header.index("Tipo de actividad")
col_file = header.index("Nombre del archivo")
col_distance = last_index(header, "Distancia")
col_moving = last_index(header, "Tiempo en movimiento")
col_elevation = last_index(header, "Desnivel positivo")

print(f"{'archivo':<16} {'dist nuestra':>12} {'Strava':>8} {'dif':>6}   "
      f"{'mov nuestro':>11} {'Strava':>7} {'dif':>5}   {'desn nuestro':>12} {'Strava':>7}")

distance_diffs, moving_diffs = [], []

for row in rows:
    year = re.search(r"20\d\d", row[col_date])
    if not (row[col_type] == "Carrera" and ".gpx" in row[col_file]
            and year and int(year.group()) >= MIN_YEAR):
        continue

    ours = parse_gpx_file(EXPORT_DIR / row[col_file])
    strava_distance = to_number(row[col_distance])
    strava_moving = to_number(row[col_moving])
    strava_elevation = to_number(row[col_elevation])

    # Si Strava diera la distancia en km (un número pequeño), la pasamos a metros
    if strava_distance is not None and strava_distance < 200:
        strava_distance *= 1000

    distance_diff = (ours.distance_m - strava_distance) / strava_distance * 100
    moving_diff = ours.moving_time_s - strava_moving
    distance_diffs.append(distance_diff)
    moving_diffs.append(moving_diff)

    print(f"{Path(row[col_file]).name:<16} {ours.distance_m:>12.0f} {strava_distance:>8.0f} "
          f"{distance_diff:>+5.1f}%   {ours.moving_time_s:>11.0f} {strava_moving:>7.0f} {moving_diff:>+5.0f}   "
          f"{ours.elevation_gain_m:>12.1f} {strava_elevation if strava_elevation is not None else '-':>7}")

print(f"\nDistancia: diferencia media {mean(distance_diffs):+.2f}%, "
      f"máxima {max(distance_diffs, key=abs):+.2f}%")
print(f"Tiempo en movimiento: diferencia media {mean(moving_diffs):+.0f} s, "
      f"máxima {max(moving_diffs, key=abs):+.0f} s")