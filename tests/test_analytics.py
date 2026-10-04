"""Tests de las consultas de análisis, contra la base de datos de tests."""

from datetime import date, datetime, timezone

import pytest

from running_coach import analytics, db
from running_coach.metrics import hr_zones
from running_coach.models import Activity, Split

TZ = "Europe/Madrid"
TODAY = date(2026, 9, 25)  # jueves: la semana actual empieza el lunes 21


def add_run(conn, start: datetime, km: float, minutes: float, hr: float | None = None,
            sport: str = "running") -> None:
    db.insert_activity(conn, Activity(
        source="manual", source_ref=f"{start.isoformat()}-{sport}", sport=sport,
        start_time=start, distance_m=km * 1000, duration_s=minutes * 60,
        moving_time_s=minutes * 60, avg_hr=hr,
    ))


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def test_empty_weeks_are_included(conn):
    add_run(conn, utc(2026, 9, 22, 18), km=5, minutes=30)

    weeks = analytics.weekly_summary(conn, weeks=4, tz=TZ, today=TODAY)

    assert [w.week_start for w in weeks] == [date(2026, 8, 31), date(2026, 9, 7),
                                             date(2026, 9, 14), date(2026, 9, 21)]
    assert [w.runs for w in weeks] == [0, 0, 0, 1]
    assert weeks[0].pace_s_per_km is None


def test_weeks_use_local_time(conn):
    # Domingo 20 a las 23:30 en Madrid (21:30 UTC): semana del 14
    add_run(conn, utc(2026, 9, 20, 21, 30), km=10, minutes=60)
    # Lunes 21 a las 00:30 en Madrid, aunque en UTC aún sea domingo: semana del 21
    add_run(conn, utc(2026, 9, 20, 22, 30), km=4, minutes=20)

    weeks = analytics.weekly_summary(conn, weeks=2, tz=TZ, today=TODAY)

    assert weeks[0].distance_m == 10_000
    assert weeks[1].distance_m == 4_000


def test_totals_pace_and_longest_run(conn):
    add_run(conn, utc(2026, 9, 21, 18), km=5, minutes=30)
    add_run(conn, utc(2026, 9, 23, 18), km=10, minutes=55)

    week = analytics.weekly_summary(conn, weeks=1, tz=TZ, today=TODAY)[0]

    assert week.runs == 2
    assert week.distance_m == 15_000
    assert week.longest_run_m == 10_000
    assert week.pace_s_per_km == pytest.approx(85 * 60 / 15)  # 85 min en 15 km = 5:40/km


def test_other_sports_are_ignored(conn):
    add_run(conn, utc(2026, 9, 22, 18), km=30, minutes=60, sport="cycling")

    assert analytics.weekly_summary(conn, weeks=1, tz=TZ, today=TODAY)[0].runs == 0


def test_avg_hr_only_counts_runs_with_heart_rate(conn):
    add_run(conn, utc(2026, 9, 21, 18), km=4, minutes=20, hr=160)
    add_run(conn, utc(2026, 9, 22, 18), km=6, minutes=30, hr=170)
    add_run(conn, utc(2026, 9, 23, 18), km=5, minutes=30)  # del móvil: sin pulsaciones

    week = analytics.weekly_summary(conn, weeks=1, tz=TZ, today=TODAY)[0]

    assert week.runs_with_hr == 2
    # Ponderada por tiempo: (160·20 + 170·30) / 50 = 166, sin contar la carrera sin FC como 0
    assert week.avg_hr == pytest.approx(166)


def test_week_without_heart_rate_has_no_average(conn):
    add_run(conn, utc(2026, 9, 21, 18), km=5, minutes=30)

    assert analytics.weekly_summary(conn, weeks=1, tz=TZ, today=TODAY)[0].avg_hr is None

def test_intensity_distribution(conn):
    run = Activity(source="manual", source_ref="con-parciales", start_time=utc(2026, 9, 22, 18),
                   distance_m=3000, duration_s=1080, moving_time_s=1080)
    run.splits = [
        Split(index=1, distance_m=1000, duration_s=360, avg_hr=140),   # Z2
        Split(index=2, distance_m=1000, duration_s=360, avg_hr=170),   # Z4
        Split(index=3, distance_m=1000, duration_s=360, avg_hr=None),  # sin pulsómetro
    ]
    db.insert_activity(conn, run)

    result = analytics.intensity_distribution(conn, hr_zones(190, 57), weeks=1, tz=TZ, today=TODAY)

    assert result.seconds_in_zone == [0, 360, 0, 360, 0]
    assert result.unmeasured_s == 360
    assert result.measured_s == 720


def test_intensity_distribution_ignores_older_runs(conn):
    old = Activity(source="manual", source_ref="antigua", start_time=utc(2026, 9, 10, 18),
                   distance_m=1000, duration_s=360, moving_time_s=360)
    old.splits = [Split(index=1, distance_m=1000, duration_s=360, avg_hr=150)]
    db.insert_activity(conn, old)

    result = analytics.intensity_distribution(conn, hr_zones(190, 57), weeks=1, tz=TZ, today=TODAY)

    assert result.measured_s == 0

def test_current_week_is_marked(conn):
    weeks = analytics.weekly_summary(conn, weeks=2, tz=TZ, today=TODAY)

    assert [w.is_current for w in weeks] == [False, True]


def test_warmup_and_run_on_the_same_day_are_one_session(conn):
    add_run(conn, utc(2026, 9, 22, 19, 27), km=1.2, minutes=8)   # calentamiento
    add_run(conn, utc(2026, 9, 22, 19, 48), km=9.9, minutes=59)  # carrera
    add_run(conn, utc(2026, 9, 24, 18), km=5, minutes=30)

    week = analytics.weekly_summary(conn, weeks=1, tz=TZ, today=TODAY)[0]

    assert week.runs == 3
    assert week.sessions == 2

def test_training_load(conn):
    run = Activity(source="manual", source_ref="carga", start_time=utc(2026, 9, 22, 18),
                   distance_m=2000, duration_s=720, moving_time_s=720)
    run.splits = [
        Split(index=1, distance_m=1000, duration_s=360, avg_hr=165),   # 6 min en Z4: carga 24
        Split(index=2, distance_m=1000, duration_s=360, avg_hr=None),  # sin pulsómetro: no suma
    ]
    db.insert_activity(conn, run)
    # Fuera de las 2 semanas de la tabla, pero dentro de los 28 días: 30 min en Z2, carga 60
    add_run(conn, utc(2026, 9, 10, 18), km=5, minutes=30, hr=140)

    report = analytics.training_load(conn, hr_zones(190, 57), weeks=2, tz=TZ, today=TODAY)

    current = report.weeks[-1]
    assert current.is_current
    assert current.trimp == pytest.approx(24)
    assert current.distance_m == 2000
    assert current.unmeasured_s == 360
    assert report.trimp.acute == pytest.approx(24)
    assert report.trimp.chronic == pytest.approx((24 + 60) / 4)

def test_recent_runs_newest_first(conn):
    add_run(conn, utc(2026, 9, 22, 18), km=5, minutes=30)
    add_run(conn, utc(2026, 9, 24, 18), km=6, minutes=36, hr=150)
    add_run(conn, utc(2026, 9, 1, 18), km=7, minutes=40)                 # fuera del periodo
    add_run(conn, utc(2026, 9, 23, 18), km=20, minutes=60, sport="cycling")

    runs = analytics.recent_runs(conn, weeks=1, tz=TZ, today=TODAY)

    assert [r.distance_m for r in runs] == [6000, 5000]
    assert runs[0].local_start == datetime(2026, 9, 24, 20, 0)  # 18:00 UTC = 20:00 en Madrid
    assert runs[0].splits == 0