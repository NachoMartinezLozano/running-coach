"""Consultas de análisis sobre las actividades guardadas."""

from dataclasses import dataclass
from datetime import date

import psycopg

from running_coach.metrics import HeartRateZone, pace_s_per_km, zone_index

WEEKLY_SUMMARY = """
    WITH weeks AS (
        -- Todas las semanas del periodo, también las que no tienen carreras
        SELECT generate_series(
                   date_trunc('week', COALESCE(%(today)s::date, (now() AT TIME ZONE %(tz)s)::date)::timestamp)
                       - (%(weeks)s::int - 1) * interval '1 week',
                   date_trunc('week', COALESCE(%(today)s::date, (now() AT TIME ZONE %(tz)s)::date)::timestamp),
                   interval '1 week'
               )::date AS week_start
    ),
    runs AS (
        -- Cada carrera, con el lunes de su semana según la hora LOCAL del atleta
        SELECT date_trunc('week', start_time AT TIME ZONE %(tz)s)::date AS week_start,
               distance_m,
               COALESCE(moving_time_s, duration_s) AS moving_s,
               avg_hr
        FROM activities
        WHERE sport = 'running'
    )
    SELECT w.week_start,
           count(r.distance_m)            AS runs,
           COALESCE(sum(r.distance_m), 0) AS distance_m,
           COALESCE(sum(r.moving_s), 0)   AS moving_time_s,
           COALESCE(max(r.distance_m), 0) AS longest_run_m,
           count(r.avg_hr)                AS runs_with_hr,
           -- FC media ponderada por tiempo, solo con las carreras que tienen pulsómetro
           sum(r.avg_hr * r.moving_s)
               / NULLIF(sum(r.moving_s) FILTER (WHERE r.avg_hr IS NOT NULL), 0) AS avg_hr
    FROM weeks w
    LEFT JOIN runs r USING (week_start)
    GROUP BY w.week_start
    ORDER BY w.week_start
"""


@dataclass
class WeekSummary:
    week_start: date  # lunes de la semana
    runs: int
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

SPLITS_IN_PERIOD = """
    SELECT s.avg_hr, s.duration_s
    FROM splits s
    JOIN activities a ON a.id = s.activity_id
    WHERE a.sport = 'running'
      AND (a.start_time AT TIME ZONE %(tz)s)::date >=
          date_trunc('week', COALESCE(%(today)s::date, (now() AT TIME ZONE %(tz)s)::date)::timestamp)::date
              - (%(weeks)s::int - 1) * 7
"""


@dataclass
class IntensityDistribution:
    zones: list[HeartRateZone]
    seconds_in_zone: list[float]  # una posición por zona
    unmeasured_s: float  # tiempo de parciales sin pulsaciones (carreras con el móvil)

    @property
    def measured_s(self) -> float:
        return sum(self.seconds_in_zone)


def intensity_distribution(conn: psycopg.Connection, zones: list[HeartRateZone], weeks: int, tz: str,
                           today: date | None = None) -> IntensityDistribution:
    """Tiempo en cada zona durante las últimas `weeks` semanas.

    Aproximación por kilómetro: cada parcial cuenta entero en la zona de su FC media.
    """
    rows = conn.execute(SPLITS_IN_PERIOD, {"weeks": weeks, "tz": tz, "today": today}).fetchall()
    seconds = [0.0] * len(zones)
    unmeasured = 0.0
    for row in rows:
        if row["avg_hr"] is None:
            unmeasured += row["duration_s"]
        else:
            seconds[zone_index(row["avg_hr"], zones)] += row["duration_s"]
    return IntensityDistribution(zones, seconds, unmeasured)