"""Casos de uso de la aplicación.

Aquí se combinan los importadores y la base de datos. La CLI, el servidor MCP
y la futura interfaz web llaman a estas funciones en lugar de repetir la lógica.
"""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
import uuid
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from running_coach import db, analytics
from running_coach.config import timezone_name
from running_coach.importers.strava_export import ImportFilters, import_strava_export
from running_coach.models import AthleteProfile, Activity, SESSION_TYPES
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

@dataclass
class ManualRunResult:
    activity: Activity | None  # None si no se guardó por posible duplicado
    similar: list[dict]  # carreras parecidas que ya había ese día


def log_manual_run(conn: psycopg.Connection, *, day: date, distance_km: float, duration_s: float,
                   start: time | None = None, avg_hr: float | None = None, max_hr: int | None = None,
                   elevation_gain_m: float | None = None, session_type: str | None = None,
                   rpe: int | None = None, notes: str | None = None, force: bool = False,
                   tz: str | None = None) -> ManualRunResult:
    """Registra una carrera introducida a mano.

    Si ese día ya hay una carrera de distancia parecida, no la guarda (salvo con force=True):
    lo más probable es que sea la misma, añadida dos veces.
    """
    if distance_km <= 0:
        raise ValueError("La distancia debe ser mayor que cero.")
    if duration_s <= 0:
        raise ValueError("La duración debe ser mayor que cero.")
    if rpe is not None and not 1 <= rpe <= 10:
        raise ValueError("El RPE debe estar entre 1 y 10.")
    if session_type is not None and session_type not in SESSION_TYPES:
        raise ValueError(f"Tipo de sesión no válido. Opciones: {', '.join(SESSION_TYPES)}")

    tz = tz or timezone_name()
    db.init_schema(conn)
    similar = db.find_similar_runs(conn, day, distance_km * 1000, tz)
    if similar and not force:
        return ManualRunResult(activity=None, similar=similar)

    # Sin hora, mediodía: así la carrera nunca cambia de día al convertirla a UTC
    local_start = datetime.combine(day, start or time(12, 0), tzinfo=ZoneInfo(tz))
    activity = Activity(
        source="manual",
        source_ref=f"manual:{uuid.uuid4()}",
        start_time=local_start,
        distance_m=distance_km * 1000,
        duration_s=duration_s,
        moving_time_s=duration_s,
        avg_hr=avg_hr,
        max_hr=max_hr,
        elevation_gain_m=elevation_gain_m,
        session_type=session_type,
        rpe=rpe,
        notes=notes,
        device="Registro manual",
    )
    db.insert_activity(conn, activity)
    return ManualRunResult(activity=activity, similar=similar)