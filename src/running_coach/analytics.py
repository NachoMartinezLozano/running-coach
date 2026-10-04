"""Consultas de análisis sobre las actividades guardadas."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg

from running_coach.metrics import (
    HeartRateZone,
    LoadRatio,
    acute_chronic,
    edwards_trimp,
    pace_s_per_km,
    period_start,
    week_start,
    zone_index,
)


def local_today(tz: str) -> date:
    """La fecha de hoy en la zona horaria del atleta."""
    return datetime.now(ZoneInfo(tz)).date()


# ---------- Resumen semanal ----------

WEEKLY_SUMMARY = """
    WITH today AS (
        -- "Hoy" en la zona horaria del atleta (o la fecha fija que pidan los tests)
        SELECT COALESCE(%(today)s::date, (now() AT TIME ZONE %(tz)s)::date) AS day
    ),
    weeks AS (
        -- Todas las semanas del periodo, también las que no tienen carreras
        SELECT g.week_start::date AS week_start,
               g.week_start = date_trunc('week', today.day::timestamp) AS is_current
        FROM today,
             generate_series(
                 date_trunc('week', today.day::timestamp) - (%(weeks)s::int - 1) * interval '1 week',
                 date_trunc('week', today.day::timestamp),
                 interval '1 week'
             ) AS g(week_start)
    ),
    runs AS (
        -- Cada carrera, con su día y el lunes de su semana según la hora LOCAL del atleta
        SELECT date_trunc('week', start_time AT TIME ZONE %(tz)s)::date AS week_start,
               (start_time AT TIME ZONE %(tz)s)::date AS local_day,
               distance_m,
               COALESCE(moving_time_s, duration_s) AS moving_s,
               avg_hr
        FROM activities
        WHERE sport = 'running'
    )
    SELECT w.week_start,
           w.is_current,
           count(r.distance_m)              AS runs,
           count(DISTINCT r.local_day)      AS sessions,
           COALESCE(sum(r.distance_m), 0)   AS distance_m,
           COALESCE(sum(r.moving_s), 0)     AS moving_time_s,
           COALESCE(max(r.distance_m), 0)   AS longest_run_m,
           count(r.avg_hr)                  AS runs_with_hr,
           -- FC media ponderada por tiempo, solo con las carreras que tienen pulsómetro
           sum(r.avg_hr * r.moving_s)
               / NULLIF(sum(r.moving_s) FILTER (WHERE r.avg_hr IS NOT NULL), 0) AS avg_hr
    FROM weeks w
    LEFT JOIN runs r USING (week_start)
    GROUP BY w.week_start, w.is_current
    ORDER BY w.week_start
"""


@dataclass
class WeekSummary:
    week_start: date  # lunes de la semana
    is_current: bool  # la semana de hoy: aún no ha terminado
    runs: int  # actividades
    sessions: int  # días distintos con carrera (calentamiento + carrera = una sesión)
    distance_m: float
    moving_time_s: float
    longest_run_m: float
    runs_with_hr: int
    avg_hr: float | None  # None si ninguna carrera de la semana tiene pulsaciones

    @property
    def pace_s_per_km(self) -> float | None:
        return pace_s_per_km(self.distance_m, self.moving_time_s)


def weekly_summary(conn: psycopg.Connection, weeks: int, tz: str,
                   today: date | None = None) -> list[WeekSummary]:
    """Resumen de las últimas `weeks` semanas (de lunes a domingo), la actual incluida."""
    rows = conn.execute(WEEKLY_SUMMARY, {"weeks": weeks, "tz": tz, "today": today}).fetchall()
    return [WeekSummary(**row) for row in rows]


# ---------- Tramos con pulsaciones: base de las zonas y de la carga ----------

HR_SEGMENTS = """
    -- Los parciales de las carreras que los tienen...
    SELECT (a.start_time AT TIME ZONE %(tz)s)::date AS day, s.avg_hr, s.duration_s, s.distance_m
    FROM splits s
    JOIN activities a ON a.id = s.activity_id
    WHERE a.sport = 'running'
      AND (a.start_time AT TIME ZONE %(tz)s)::date >= %(first_day)s
    UNION ALL
    -- ...y las carreras sin parciales (registro manual), como un único tramo
    SELECT (a.start_time AT TIME ZONE %(tz)s)::date, a.avg_hr,
           COALESCE(a.moving_time_s, a.duration_s), a.distance_m
    FROM activities a
    WHERE a.sport = 'running'
      AND (a.start_time AT TIME ZONE %(tz)s)::date >= %(first_day)s
      AND NOT EXISTS (SELECT 1 FROM splits s WHERE s.activity_id = a.id)
"""


@dataclass
class Segment:
    """Un tramo de carrera: un parcial, o una carrera entera si no tiene parciales."""

    day: date  # día local
    avg_hr: float | None
    duration_s: float
    distance_m: float


def hr_segments(conn: psycopg.Connection, first_day: date, tz: str) -> list[Segment]:
    rows = conn.execute(HR_SEGMENTS, {"first_day": first_day, "tz": tz}).fetchall()
    return [Segment(**row) for row in rows]


# ---------- Zonas de pulsaciones ----------

@dataclass
class IntensityDistribution:
    zones: list[HeartRateZone]
    seconds_in_zone: list[float]  # una posición por zona
    unmeasured_s: float  # tiempo sin pulsaciones (carreras con el móvil o registradas sin FC)

    @property
    def measured_s(self) -> float:
        return sum(self.seconds_in_zone)


def intensity_distribution(conn: psycopg.Connection, zones: list[HeartRateZone], weeks: int, tz: str,
                           today: date | None = None) -> IntensityDistribution:
    """Tiempo en cada zona durante las últimas `weeks` semanas.

    Aproximación por kilómetro: cada parcial cuenta entero en la zona de su FC media.
    Las carreras registradas a mano, sin parciales, cuentan enteras en la zona de su FC media.
    """
    today = today or local_today(tz)
    seconds = [0.0] * len(zones)
    unmeasured = 0.0
    for segment in hr_segments(conn, period_start(today, weeks), tz):
        if segment.avg_hr is None:
            unmeasured += segment.duration_s
        else:
            seconds[zone_index(segment.avg_hr, zones)] += segment.duration_s
    return IntensityDistribution(zones, seconds, unmeasured)


# ---------- Carga de entrenamiento ----------

@dataclass
class WeekLoad:
    week_start: date
    is_current: bool
    trimp: float  # carga (TRIMP de Edwards) de los tramos con pulsaciones
    distance_m: float
    unmeasured_s: float  # tiempo sin pulsaciones: no suma carga


@dataclass
class TrainingLoad:
    weeks: list[WeekLoad]
    trimp: LoadRatio  # relación aguda/crónica de la carga
    distance: LoadRatio  # relación aguda/crónica de los kilómetros


def training_load(conn: psycopg.Connection, zones: list[HeartRateZone], weeks: int, tz: str,
                  today: date | None = None) -> TrainingLoad:
    """Carga semanal y relación aguda/crónica (últimos 7 días frente a la media de 28)."""
    today = today or local_today(tz)
    first_week = period_start(today, weeks)
    # La relación aguda/crónica necesita los últimos 28 días, aunque se pidan menos semanas
    first_day = min(first_week, today - timedelta(days=27))

    daily_trimp: dict[date, float] = defaultdict(float)
    daily_distance: dict[date, float] = defaultdict(float)
    unmeasured_by_week: dict[date, float] = defaultdict(float)
    for s in hr_segments(conn, first_day, tz):
        if s.day > today:
            continue
        daily_distance[s.day] += s.distance_m
        if s.avg_hr is None:
            unmeasured_by_week[week_start(s.day)] += s.duration_s
        else:
            daily_trimp[s.day] += edwards_trimp(s.duration_s, s.avg_hr, zones)

    week_list = []
    for i in range(weeks):
        monday = first_week + timedelta(weeks=i)
        days = [monday + timedelta(days=d) for d in range(7)]
        week_list.append(WeekLoad(
            week_start=monday,
            is_current=monday == week_start(today),
            trimp=sum(daily_trimp.get(d, 0.0) for d in days),
            distance_m=sum(daily_distance.get(d, 0.0) for d in days),
            unmeasured_s=unmeasured_by_week.get(monday, 0.0),
        ))
    return TrainingLoad(weeks=week_list,
                        trimp=acute_chronic(daily_trimp, today),
                        distance=acute_chronic(daily_distance, today))

# ---------- Carreras recientes ----------

RECENT_RUNS = """
    SELECT a.id,
           a.start_time AT TIME ZONE %(tz)s AS local_start,
           a.device,
           a.distance_m,
           COALESCE(a.moving_time_s, a.duration_s) AS moving_time_s,
           a.avg_hr,
           a.max_hr,
           a.elevation_gain_m,
           a.session_type,
           a.rpe,
           a.notes,
           (SELECT count(*) FROM splits s WHERE s.activity_id = a.id) AS splits
    FROM activities a
    WHERE a.sport = 'running'
      AND (a.start_time AT TIME ZONE %(tz)s)::date >= %(first_day)s
    ORDER BY a.start_time DESC
"""


@dataclass
class RunSummary:
    id: int
    local_start: datetime  # hora local del atleta, sin zona horaria
    device: str | None
    distance_m: float
    moving_time_s: float
    avg_hr: float | None
    max_hr: int | None
    elevation_gain_m: float | None
    session_type: str | None
    rpe: int | None
    notes: str | None
    splits: int  # número de parciales por km (0 en los registros manuales)

    @property
    def pace_s_per_km(self) -> float | None:
        return pace_s_per_km(self.distance_m, self.moving_time_s)


def recent_runs(conn: psycopg.Connection, weeks: int, tz: str, today: date | None = None) -> list[RunSummary]:
    """Carreras de las últimas `weeks` semanas, de la más reciente a la más antigua."""
    today = today or local_today(tz)
    rows = conn.execute(RECENT_RUNS, {"first_day": period_start(today, weeks), "tz": tz}).fetchall()
    return [RunSummary(**row) for row in rows]