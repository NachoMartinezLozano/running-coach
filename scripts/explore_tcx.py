"""Exploración de los TCX de carrera: qué datos trae cada archivo.

No imprime coordenadas ni fechas: solo recuentos, porcentajes y totales de las vueltas.
Uso: uv run python scripts/explore_tcx.py
"""

import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from running_coach.importers.common import read_file_bytes, xml_local_name
from running_coach.importers.strava_csv import read_activities_csv

EXPORT_DIR = Path("data/strava_export")

records = read_activities_csv(EXPORT_DIR / "activities.csv")
tcx_runs = [r for r in records if r.sport == "running" and r.filename and ".tcx" in r.filename]


def pct(n: int, total: int) -> str:
    return f"{n / total:.0%}" if total else "-"


print(f"{'archivo':<18} {'creador':<26} {'deporte':<8} {'vueltas':>7} {'puntos':>6} "
      f"{'pos':>5} {'alt':>5} {'dist':>5} {'hr':>5} {'cad':>5}")

all_tags = Counter()
first_lap_summary = None

for record in tcx_runs:
    # .strip(): algunos TCX traen espacios antes de la cabecera XML, y el parser los rechaza
    root = ET.fromstring(read_file_bytes(EXPORT_DIR / record.filename).strip())
    elements = list(root.iter())

    activity = next((e for e in elements if xml_local_name(e.tag) == "Activity"), None)
    sport = activity.get("Sport", "?") if activity is not None else "?"

    creator = next((e for e in elements if xml_local_name(e.tag) == "Creator"), None)
    creator_name = "?"
    if creator is not None:
        name = next((e for e in creator.iter() if xml_local_name(e.tag) == "Name"), None)
        creator_name = name.text if name is not None else "?"

    laps = [e for e in elements if xml_local_name(e.tag) == "Lap"]
    points = [e for e in elements if xml_local_name(e.tag) == "Trackpoint"]

    coverage = Counter()
    for point in points:
        coverage.update({xml_local_name(c.tag) for c in point.iter() if c is not point})
    all_tags.update(coverage)

    # Guardamos el resumen de la primera vuelta del primer archivo para verlo
    if first_lap_summary is None and laps:
        first_lap_summary = [(xml_local_name(c.tag), (c.text or "").strip())
                             for c in laps[0] if xml_local_name(c.tag) != "Track"]

    total = len(points)
    cadence = max(coverage["Cadence"], coverage["RunCadence"])
    print(f"{Path(record.filename).name:<18} {creator_name[:26]:<26} {sport:<8} {len(laps):>7} {total:>6} "
          f"{pct(coverage['LatitudeDegrees'], total):>5} {pct(coverage['AltitudeMeters'], total):>5} "
          f"{pct(coverage['DistanceMeters'], total):>5} {pct(coverage['Value'], total):>5} "
          f"{pct(cadence, total):>5}")

print("\nEtiquetas dentro de los puntos (todos los archivos):")
for tag, n in all_tags.most_common():
    print(f"  {tag:<22} {n:6}")

print("\nResumen de la primera vuelta del primer archivo:")
for tag, text in first_lap_summary or []:
    print(f"  {tag:<24} {text}")