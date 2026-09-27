"""Compara nuestros parciales con las vueltas automáticas que guarda el reloj.

Uso: uv run python scripts/compare_splits.py [ruta_a_un_archivo.fit o .fit.gz]
"""

import io
import sys
from pathlib import Path

import fitdecode

from running_coach.importers.common import read_file_bytes
from running_coach.importers.fit_importer import parse_fit_file


def pace(distance_m, seconds) -> str:
    if not distance_m or seconds is None:
        return "-"
    s = round(seconds / (distance_m / 1000))
    return f"{s // 60}:{s % 60:02d}"


def fmt(value, width, decimals=0) -> str:
    return f"{value:>{width}.{decimals}f}" if value is not None else f"{'-':>{width}}"


path = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted(
    Path("data/strava_export/activities").glob("*.fit.gz"))[-1]
activity = parse_fit_file(path)

laps = []
with fitdecode.FitReader(io.BytesIO(read_file_bytes(path))) as fit:
    for frame in fit:
        if isinstance(frame, fitdecode.FitDataMessage) and frame.name == "lap":
            laps.append({
                "distance": frame.get_value("total_distance", fallback=None),
                "time": frame.get_value("total_timer_time", fallback=None),
                "hr": frame.get_value("avg_heart_rate", fallback=None),
            })

print(f"Actividad: {activity.sport}, {activity.distance_m / 1000:.2f} km\n")
print(f"{'':>3}   {'NUESTROS PARCIALES':<30}   {'VUELTAS DEL RELOJ':<22}")
print(f"{'km':>3}   {'dist':>7} {'ritmo':>6} {'FC':>6} {'desniv':>7}   {'dist':>7} {'ritmo':>6} {'FC':>5}")
for i in range(max(len(activity.splits), len(laps))):
    s = activity.splits[i] if i < len(activity.splits) else None
    lap = laps[i] if i < len(laps) else None
    ours = (f"{fmt(s.distance_m, 7)} {pace(s.distance_m, s.duration_s):>6} "
            f"{fmt(s.avg_hr, 6, 1)} {fmt(s.elevation_change_m, 7, 1)}") if s else " " * 29
    watch = (f"{fmt(lap['distance'], 7)} {pace(lap['distance'], lap['time']):>6} "
             f"{fmt(lap['hr'], 5)}") if lap else ""
    print(f"{i + 1:>3}   {ours}   {watch}")