"""Diagnóstico: ¿de dónde sale la distancia de más en los GPX del móvil?

Clasifica cada tramo entre dos puntos según su velocidad y mide cuánta
distancia y tiempo se acumulan estando parado (tramos lentos) o en saltos del GPS.
Uso: uv run python scripts/diagnose_gpx.py [año_mínimo]   (por defecto, 2025)
"""

import csv
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from running_coach.importers.common import (
    fill_distances,
    moving_time_series,
    read_file_bytes,
    xml_local_name,
)
from running_coach.importers.gpx_importer import _trkpt_to_point

EXPORT_DIR = Path("data/strava_export")
MIN_YEAR = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
SLOW_MS = 1.0   # por debajo: parado, aunque el GPS se mueva
SPIKE_MS = 7.0  # por encima: salto del GPS, imposible corriendo


def last_index(header: list[str], name: str) -> int:
    return max(i for i, col in enumerate(header) if col == name)


def to_number(text: str) -> float | None:
    text = text.strip()
    if not text:
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")
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

print(f"{'archivo':<16} {'dist de más':>11} {'en lentos':>9} {'en saltos':>9} {'nº saltos':>9}   "
      f"{'tiempo de más':>13} {'en lentos':>9}")

for row in rows:
    year = re.search(r"20\d\d", row[col_date])
    if not (row[col_type] == "Carrera" and ".gpx" in row[col_file]
            and year and int(year.group()) >= MIN_YEAR):
        continue

    # Reconstruimos los puntos igual que el importador
    root = ET.fromstring(read_file_bytes(EXPORT_DIR / row[col_file]))
    points = [_trkpt_to_point(el) for el in root.iter() if xml_local_name(el.tag) == "trkpt"]
    points = sorted((p for p in points if p is not None), key=lambda p: p.time)
    fill_distances(points)

    strava_distance = to_number(row[col_distance])
    if strava_distance < 200:
        strava_distance *= 1000
    extra_distance = points[-1].distance_m - strava_distance
    extra_moving = moving_time_series(points)[-1] - to_number(row[col_moving])

    slow_m = slow_s = spike_m = 0.0
    spikes = 0
    for a, b in zip(points, points[1:]):
        dt = (b.time - a.time).total_seconds()
        if dt <= 0:
            continue
        d = b.distance_m - a.distance_m
        speed = d / dt
        if speed < SLOW_MS:
            slow_m += d
            slow_s += dt
        elif speed > SPIKE_MS:
            spike_m += d
            spikes += 1

    print(f"{Path(row[col_file]).name:<16} {extra_distance:>10.0f}m {slow_m:>8.0f}m {spike_m:>8.0f}m "
          f"{spikes:>9}   {extra_moving:>12.0f}s {slow_s:>8.0f}s")