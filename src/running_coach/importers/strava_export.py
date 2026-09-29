"""Importa la exportación completa de Strava: los archivos de actividad y el activities.csv."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from running_coach.importers.files import activity_format, parse_activity_file
from running_coach.importers.strava_csv import StravaCsvRecord, read_activities_csv
from running_coach.models import Activity

# Formatos sin resumen del dispositivo: sus totales se toman de Strava (ver _merge_csv)
FORMATS_WITHOUT_DEVICE_SUMMARY = {".gpx"}


@dataclass
class ImportFilters:
    """Qué actividades entran. Los valores por defecto están pensados para carreras."""

    since: date | None = None  # fecha local mínima (inclusive)
    sports: frozenset[str] = frozenset({"running"})
    min_distance_m: float = 500  # por debajo, no es una carrera (p. ej. el reloj arrancado por error)
    min_moving_time_s: float = 180


@dataclass
class ImportResult:
    activities: list[Activity] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)  # motivo -> número de actividades
    errors: list[str] = field(default_factory=list)


def import_strava_export(export_dir: Path, filters: ImportFilters | None = None) -> ImportResult:
    """Lee la exportación y devuelve las actividades que pasan los filtros, ya combinadas con el CSV."""
    filters = filters or ImportFilters()
    result = ImportResult()

    for record in read_activities_csv(export_dir / "activities.csv"):
        # Filtros baratos primero: con el CSV sabemos el deporte sin abrir el archivo
        if record.sport not in filters.sports:
            result.skipped["otro deporte"] += 1
            continue
        if not record.filename:
            result.skipped["sin archivo"] += 1
            continue

        path = export_dir / record.filename
        try:
            activity = parse_activity_file(path)
        except Exception as exc:  # un archivo dañado no debe detener toda la importación
            result.errors.append(f"{record.filename}: {exc}")
            continue

        _merge_csv(activity, record, path)

        # Filtros que necesitan el archivo: la fecha exacta y los totales
        if filters.since and activity.start_time.astimezone().date() < filters.since:
            result.skipped["anterior a la fecha"] += 1
            continue
        moving = activity.moving_time_s or activity.duration_s
        if activity.distance_m < filters.min_distance_m or moving < filters.min_moving_time_s:
            result.skipped["demasiado corta"] += 1
            continue

        result.activities.append(activity)

    result.activities.sort(key=lambda a: a.start_time)
    return result


def _merge_csv(activity: Activity, record: StravaCsvRecord, path: Path) -> None:
    """Completa la actividad con lo que solo sabe Strava."""
    activity.sport = record.sport  # el tipo del CSV incluye las correcciones hechas en Strava
    activity.notes = record.notes
    if record.perceived_exertion is not None and 1 <= record.perceived_exertion <= 10:
        activity.rpe = record.perceived_exertion

    # Los GPX (carreras grabadas con el móvil) no traen resumen del dispositivo, y nuestros
    # totales calculados desde los puntos se desvían de los de Strava: cuentan los ratos
    # caminando por cansancio, los ratos parado con la app grabando y las desviaciones del
    # GPS. Strava limpia todo eso, así que para estos archivos usamos sus totales.
    # Los parciales siguen saliendo de los puntos.
    if activity_format(path) in FORMATS_WITHOUT_DEVICE_SUMMARY:
        if record.distance_m:
            activity.distance_m = record.distance_m
        if record.moving_time_s:
            activity.moving_time_s = record.moving_time_s
        if record.elevation_gain_m is not None:
            activity.elevation_gain_m = record.elevation_gain_m