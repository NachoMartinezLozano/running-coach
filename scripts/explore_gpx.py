"""Exploración de los GPX de carrera: qué datos trae cada archivo.

No imprime coordenadas ni fechas concretas: solo recuentos y porcentajes.
Uso: uv run python scripts/explore_gpx.py [año_mínimo]   (por defecto, 2025)
"""

import csv
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import median

from running_coach.importers.common import read_file_bytes

EXPORT_DIR = Path("data/strava_export")
MIN_YEAR = int(sys.argv[1]) if len(sys.argv) > 1 else 2025


def local(tag: str) -> str:
    """'{http://www.topografix.com/GPX/1/1}trkpt' -> 'trkpt'"""
    return tag.rsplit("}", 1)[-1]


def running_gpx_files() -> list[Path]:
    """Carreras en GPX desde MIN_YEAR, según el CSV de la exportación."""
    files = []
    with open(EXPORT_DIR / "activities.csv", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        col_date = header.index("Fecha de la actividad")
        col_type = header.index("Tipo de actividad")
        col_file = header.index("Nombre del archivo")
        for row in reader:
            year = re.search(r"20\d\d", row[col_date])
            if (row[col_type] == "Carrera" and ".gpx" in row[col_file]
                    and year and int(year.group()) >= MIN_YEAR):
                files.append(EXPORT_DIR / row[col_file])
    return sorted(files)


def pct(n: int, total: int) -> str:
    return f"{n / total:.0%}" if total else "-"


all_point_tags = Counter()  # etiquetas vistas dentro de los puntos, en todos los archivos

print(f"{'archivo':<16} {'creador':<22} {'tipo':<10} {'puntos':>6} {'cada':>5} "
      f"{'ele':>5} {'time':>5} {'hr':>5} {'cad':>5}")

for path in running_gpx_files():
    root = ET.fromstring(read_file_bytes(path))
    points = [el for el in root.iter() if local(el.tag) == "trkpt"]
    total = len(points)

    # Para cada punto, qué etiquetas contiene (ele, time, hr, cad...)
    coverage = Counter()
    for point in points:
        tags_in_point = {local(child.tag) for child in point.iter() if child is not point}
        coverage.update(tags_in_point)
    all_point_tags.update(coverage)

    # Frecuencia de muestreo: mediana de segundos entre puntos consecutivos
    times = [datetime.fromisoformat(el.text) for el in root.iter()
             if local(el.tag) == "time" and el.text and el in {c for p in points for c in p}]
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
    sampling = f"{median(gaps):.0f}s" if gaps else "-"

    track_type = next((el.text for el in root.iter() if local(el.tag) == "type"), "-")
    creator = root.get("creator", "?")[:22]

    print(f"{path.name:<16} {creator:<22} {track_type:<10} {total:>6} {sampling:>5} "
          f"{pct(coverage['ele'], total):>5} {pct(coverage['time'], total):>5} "
          f"{pct(coverage['hr'], total):>5} {pct(coverage['cad'], total):>5}")

print("\nEtiquetas encontradas dentro de los puntos (todos los archivos):")
for tag, n in all_point_tags.most_common():
    print(f"  {tag:<24} {n:6}")