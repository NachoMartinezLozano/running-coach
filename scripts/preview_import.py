"""Vista previa de la importación: qué carreras entrarían y por qué se descartan las demás.

Uso: uv run python scripts/preview_import.py [fecha_mínima]   (por defecto, 2025-01-01)
"""

import sys
from datetime import date
from pathlib import Path

from running_coach.importers.strava_export import ImportFilters, import_strava_export

since = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2025, 1, 1)
result = import_strava_export(Path("data/strava_export"), ImportFilters(since=since))


def clock(seconds: float | None) -> str:
    """3725 -> '1:02:05'; 305 -> '5:05'"""
    if seconds is None:
        return "-"
    minutes, s = divmod(round(seconds), 60)
    h, m = divmod(minutes, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def pace(distance_m: float, seconds: float | None) -> str:
    if not distance_m or seconds is None:
        return "-"
    return clock(seconds / (distance_m / 1000))


print(f"{'fecha':<16}  {'dispositivo':<24} {'km':>6} {'tiempo':>8} {'ritmo':>6} "
      f"{'FC':>6} {'parc':>4} {'RPE':>3}  notas")
for a in result.activities:
    moving = a.moving_time_s or a.duration_s
    hr = f"{a.avg_hr:.0f}" if a.avg_hr is not None else "-"
    rpe = a.rpe if a.rpe is not None else "-"
    print(f"{a.start_time.astimezone():%Y-%m-%d %H:%M}  {(a.device or '-')[:24]:<24} "
          f"{a.distance_m / 1000:>6.2f} {clock(moving):>8} {pace(a.distance_m, moving):>6} "
          f"{hr:>6} {len(a.splits):>4} {rpe:>3}  {'sí' if a.notes else ''}")

print(f"\nImportadas: {len(result.activities)}")
for reason, n in result.skipped.most_common():
    print(f"Descartadas ({reason}): {n}")
for error in result.errors:
    print(f"ERROR: {error}")