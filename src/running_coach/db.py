"""Acceso a la base de datos PostgreSQL."""

from collections.abc import Iterable
from importlib.resources import files

import psycopg
from psycopg.rows import dict_row

from running_coach.config import database_url
from running_coach.models import Activity, AthleteProfile

INSERT_ACTIVITY = """
    INSERT INTO activities (
        source, source_ref, sport, device, start_time,
        distance_m, duration_s, moving_time_s, avg_hr, max_hr, avg_cadence, elevation_gain_m,
        session_type, rpe, notes
    ) VALUES (
        %(source)s, %(source_ref)s, %(sport)s, %(device)s, %(start_time)s,
        %(distance_m)s, %(duration_s)s, %(moving_time_s)s, %(avg_hr)s, %(max_hr)s,
        %(avg_cadence)s, %(elevation_gain_m)s,
        %(session_type)s, %(rpe)s, %(notes)s
    )
    ON CONFLICT (source_ref) DO NOTHING
    RETURNING id
"""

INSERT_SPLIT = """
    INSERT INTO splits (activity_id, split_index, distance_m, duration_s, avg_hr, elevation_change_m)
    VALUES (%s, %s, %s, %s, %s, %s)
"""

PROFILE_FIELDS = ("max_hr", "resting_hr", "sex", "goal", "goal_date", "weekly_days", "notes")

# Solo cambia los campos que se pasan: COALESCE conserva el valor guardado si el nuevo es NULL
UPSERT_PROFILE = """
    INSERT INTO athlete_profile (id, max_hr, resting_hr, sex, goal, goal_date, weekly_days, notes)
    VALUES (TRUE, %(max_hr)s, %(resting_hr)s, %(sex)s, %(goal)s, %(goal_date)s, %(weekly_days)s, %(notes)s)
    ON CONFLICT (id) DO UPDATE SET
        max_hr      = COALESCE(EXCLUDED.max_hr, athlete_profile.max_hr),
        resting_hr  = COALESCE(EXCLUDED.resting_hr, athlete_profile.resting_hr),
        sex         = COALESCE(EXCLUDED.sex, athlete_profile.sex),
        goal        = COALESCE(EXCLUDED.goal, athlete_profile.goal),
        goal_date   = COALESCE(EXCLUDED.goal_date, athlete_profile.goal_date),
        weekly_days = COALESCE(EXCLUDED.weekly_days, athlete_profile.weekly_days),
        notes       = COALESCE(EXCLUDED.notes, athlete_profile.notes),
        updated_at  = now()
"""


def connect(conninfo: str | None = None) -> psycopg.Connection:
    """Abre una conexión. Cada operación de escritura define su propia transacción."""
    return psycopg.connect(conninfo or database_url(), autocommit=True, row_factory=dict_row)


def init_schema(conn: psycopg.Connection) -> None:
    """Crea las tablas si no existen, a partir de schema.sql."""
    sql = files("running_coach").joinpath("schema.sql").read_text(encoding="utf-8")
    conn.execute(sql)


def insert_activity(conn: psycopg.Connection, activity: Activity) -> int | None:
    """Guarda una actividad con sus parciales. Devuelve su id, o None si ya existía."""
    with conn.transaction():
        row = conn.execute(INSERT_ACTIVITY, _activity_params(activity)).fetchone()
        if row is None:
            return None  # ON CONFLICT: ese source_ref ya estaba guardado
        activity_id = row["id"]
        with conn.cursor() as cur:
            cur.executemany(INSERT_SPLIT, [
                (activity_id, s.index, s.distance_m, s.duration_s, s.avg_hr, s.elevation_change_m)
                for s in activity.splits
            ])
    activity.id = activity_id
    return activity_id


def save_activities(conn: psycopg.Connection, activities: Iterable[Activity]) -> tuple[int, int]:
    """Guarda varias actividades. Devuelve (nuevas, duplicadas)."""
    inserted = duplicates = 0
    for activity in activities:
        if insert_activity(conn, activity) is None:
            duplicates += 1
        else:
            inserted += 1
    return inserted, duplicates


def _activity_params(a: Activity) -> dict:
    return {
        "source": a.source,
        "source_ref": a.source_ref,
        "sport": a.sport,
        "device": a.device,
        "start_time": a.start_time,
        "distance_m": round(a.distance_m, 1),  # precisión de GPS, no de nanómetros
        "duration_s": a.duration_s,
        "moving_time_s": a.moving_time_s,
        "avg_hr": a.avg_hr,
        "max_hr": a.max_hr,
        "avg_cadence": a.avg_cadence,
        "elevation_gain_m": a.elevation_gain_m,
        "session_type": a.session_type,
        "rpe": a.rpe,
        "notes": a.notes,
    }

def get_profile(conn: psycopg.Connection) -> AthleteProfile:
    """Devuelve el perfil guardado, o un perfil vacío si aún no se ha configurado."""
    row = conn.execute("SELECT * FROM athlete_profile WHERE id").fetchone()
    if row is None:
        return AthleteProfile()
    row.pop("id")
    return AthleteProfile(**row)


def update_profile(conn: psycopg.Connection, **fields) -> AthleteProfile:
    """Actualiza solo los campos indicados (los que valen None no se tocan)."""
    unknown = set(fields) - set(PROFILE_FIELDS)
    if unknown:
        raise ValueError(f"Campos de perfil desconocidos: {sorted(unknown)}")
    params = {name: fields.get(name) for name in PROFILE_FIELDS}
    conn.execute(UPSERT_PROFILE, params)
    return get_profile(conn)

SIMILAR_RUNS = """
    SELECT id, start_time, distance_m
    FROM activities
    WHERE sport = 'running'
      AND (start_time AT TIME ZONE %(tz)s)::date = %(day)s
      AND abs(distance_m - %(distance_m)s) <= %(tolerance)s * %(distance_m)s
"""


def find_similar_runs(conn: psycopg.Connection, day, distance_m: float, tz: str,
                      tolerance: float = 0.1) -> list[dict]:
    """Carreras del mismo día (hora local) con una distancia parecida: posibles duplicados."""
    return conn.execute(SIMILAR_RUNS, {"day": day, "distance_m": distance_m, "tz": tz,
                                       "tolerance": tolerance}).fetchall()