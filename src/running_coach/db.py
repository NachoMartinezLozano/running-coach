"""Acceso a la base de datos PostgreSQL."""

from collections.abc import Iterable
from importlib.resources import files

import psycopg
from psycopg.rows import dict_row

from running_coach.config import database_url
from running_coach.models import Activity, AthleteProfile, PlannedSession, TrainingPlan

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

def delete_activity(conn: psycopg.Connection, activity_id: int) -> dict | None:
    """Borra una actividad (y sus parciales, por el ON DELETE CASCADE). Devuelve lo borrado o None."""
    return conn.execute(
        "DELETE FROM activities WHERE id = %s RETURNING id, start_time, distance_m",
        (activity_id,),
    ).fetchone()

# ---------- Planes de entrenamiento ----------

SESSION_COLUMNS = ("day", "session_type", "description", "target_distance_m", "target_duration_s",
                   "target_pace_fast_s", "target_pace_slow_s", "target_hr_zone")

INSERT_PLAN = """
    INSERT INTO training_plans (name, goal, start_date, end_date, notes)
    VALUES (%(name)s, %(goal)s, %(start_date)s, %(end_date)s, %(notes)s)
    RETURNING id
"""

INSERT_SESSION = """
    INSERT INTO planned_sessions (plan_id, day, session_type, description, target_distance_m,
                                  target_duration_s, target_pace_fast_s, target_pace_slow_s, target_hr_zone)
    VALUES (%(plan_id)s, %(day)s, %(session_type)s, %(description)s, %(target_distance_m)s,
            %(target_duration_s)s, %(target_pace_fast_s)s, %(target_pace_slow_s)s, %(target_hr_zone)s)
    RETURNING id
"""

SELECT_SESSIONS = """
    SELECT id, day, session_type, description, target_distance_m, target_duration_s,
           target_pace_fast_s, target_pace_slow_s, target_hr_zone
    FROM planned_sessions
    WHERE plan_id = %s
    ORDER BY day, id
"""


def create_plan(conn: psycopg.Connection, plan: TrainingPlan) -> int:
    """Guarda un plan como activo y archiva el que hubiera, todo en una transacción."""
    with conn.transaction():
        conn.execute("UPDATE training_plans SET status = 'archived' WHERE status = 'active'")
        plan.id = conn.execute(INSERT_PLAN, {"name": plan.name, "goal": plan.goal, "start_date": plan.start_date,
                                             "end_date": plan.end_date, "notes": plan.notes}).fetchone()["id"]
        _insert_sessions(conn, plan.id, plan.sessions)
    plan.status = "active"
    return plan.id


def get_active_plan(conn: psycopg.Connection) -> TrainingPlan | None:
    row = conn.execute("SELECT id, name, goal, start_date, end_date, status, notes "
                       "FROM training_plans WHERE status = 'active'").fetchone()
    if row is None:
        return None
    sessions = conn.execute(SELECT_SESSIONS, (row["id"],)).fetchall()
    return TrainingPlan(**row, sessions=[PlannedSession(**s) for s in sessions])


def replace_sessions_from(conn: psycopg.Connection, plan_id: int, from_day,
                          sessions: list[PlannedSession]) -> int:
    """Sustituye las sesiones del plan a partir de `from_day` (incluido). Devuelve cuántas se borraron."""
    with conn.transaction():
        deleted = conn.execute("DELETE FROM planned_sessions WHERE plan_id = %s AND day >= %s",
                               (plan_id, from_day)).rowcount
        _insert_sessions(conn, plan_id, sessions)
    return deleted


def _insert_sessions(conn: psycopg.Connection, plan_id: int, sessions: list[PlannedSession]) -> None:
    for s in sessions:
        params = {column: getattr(s, column) for column in SESSION_COLUMNS}
        s.id = conn.execute(INSERT_SESSION, {"plan_id": plan_id, **params}).fetchone()["id"]