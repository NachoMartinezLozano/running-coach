"""Casos de uso de la aplicación.

Aquí se combinan los importadores y la base de datos. La CLI, el servidor MCP
y la futura interfaz web llaman a estas funciones en lugar de repetir la lógica.
"""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

from running_coach import db, analytics
from running_coach.config import timezone_name
from running_coach.importers.strava_export import ImportFilters, import_strava_export
from running_coach.models import AthleteProfile, Activity
from running_coach.metrics import HeartRateZone, hr_zones
from running_coach.importers.files import parse_activity_file


@dataclass
class ImportSummary:
    inserted: int = 0
    duplicates: int = 0
    skipped: Counter = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)


def import_strava_export_into_db(conn: psycopg.Connection, export_dir: Path,
                                 filters: ImportFilters) -> ImportSummary:
    """Lee la exportación de Strava y guarda en la base de datos las actividades nuevas."""
    result = import_strava_export(export_dir, filters)
    db.init_schema(conn)
    inserted, duplicates = db.save_activities(conn, result.activities)
    return ImportSummary(inserted=inserted, duplicates=duplicates,
                         skipped=result.skipped, errors=result.errors)

def weekly_summary(conn: psycopg.Connection, weeks: int = 12) -> list[analytics.WeekSummary]:
    """Resumen semanal de las últimas semanas, en la zona horaria del atleta."""
    return analytics.weekly_summary(conn, weeks, tz=timezone_name())

def get_profile(conn: psycopg.Connection) -> AthleteProfile:
    return db.get_profile(conn)


def update_profile(conn: psycopg.Connection, **fields) -> AthleteProfile:
    return db.update_profile(conn, **fields)

class ProfileIncompleteError(Exception):
    """Falta un dato del perfil necesario para un cálculo."""


def heart_rate_zones(conn: psycopg.Connection) -> list[HeartRateZone]:
    profile = db.get_profile(conn)
    if profile.max_hr is None:
        raise ProfileIncompleteError("Falta la FC máxima en el perfil.")
    return hr_zones(profile.max_hr, profile.resting_hr)


def intensity_distribution(conn: psycopg.Connection, weeks: int = 12) -> analytics.IntensityDistribution:
    """Tiempo en cada zona de FC durante las últimas semanas."""
    return analytics.intensity_distribution(conn, heart_rate_zones(conn), weeks, tz=timezone_name())

def add_activity_file(conn: psycopg.Connection, path: Path) -> tuple[Activity, int | None]:
    """Añade una actividad desde un archivo suelto (.fit, .gpx o .tcx, comprimido o no).

    Devuelve la actividad leída y su id, o None como id si ya estaba guardada.
    """
    activity = parse_activity_file(path, source="fit_upload")
    db.init_schema(conn)
    return activity, db.insert_activity(conn, activity)