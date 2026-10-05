"""Tests de los planes de entrenamiento: guardar, replanificar y comparar con lo realizado."""

from datetime import date, datetime, timezone

import psycopg
import pytest

from running_coach import analytics, db, service
from running_coach.models import Activity, PlannedSession, TrainingPlan

TZ = "Europe/Madrid"


def make_plan(name: str = "10K enero", sessions: list[PlannedSession] | None = None) -> TrainingPlan:
    return TrainingPlan(
        name=name, start_date=date(2026, 10, 5), end_date=date(2027, 1, 8), goal="10 km",
        sessions=sessions if sessions is not None else [
            PlannedSession(day=date(2026, 10, 6), session_type="easy", description="Rodaje suave",
                           target_distance_m=6000, target_hr_zone=2),
            PlannedSession(day=date(2026, 10, 8), session_type="intervals", description="6 x 800 m",
                           target_pace_fast_s=320, target_pace_slow_s=330),
            PlannedSession(day=date(2026, 10, 10), session_type="long", description="Tirada larga",
                           target_distance_m=9000),
        ],
    )


def add_run(conn, start: datetime, km: float, minutes: float, hr: float | None = None) -> None:
    db.insert_activity(conn, Activity(source="manual", source_ref=start.isoformat(), start_time=start,
                                      distance_m=km * 1000, duration_s=minutes * 60,
                                      moving_time_s=minutes * 60, avg_hr=hr))


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def test_save_and_read_the_active_plan(conn):
    service.save_training_plan(conn, make_plan())

    plan = db.get_active_plan(conn)

    assert plan.name == "10K enero"
    assert [s.session_type for s in plan.sessions] == ["easy", "intervals", "long"]
    assert plan.sessions[1].target_pace_fast_s == 320


def test_new_plan_archives_the_previous_one(conn):
    service.save_training_plan(conn, make_plan("Primero"))
    service.save_training_plan(conn, make_plan("Segundo"))

    rows = conn.execute("SELECT name, status FROM training_plans ORDER BY id").fetchall()

    assert [(r["name"], r["status"]) for r in rows] == [("Primero", "archived"), ("Segundo", "active")]


def test_database_allows_only_one_active_plan(conn):
    service.save_training_plan(conn, make_plan())

    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("INSERT INTO training_plans (name, start_date, end_date) "
                     "VALUES ('Otro', '2026-10-05', '2026-12-01')")


def test_sessions_outside_the_plan_are_rejected(conn):
    plan = make_plan(sessions=[PlannedSession(day=date(2027, 2, 1), session_type="easy", description="Fuera")])

    with pytest.raises(ValueError, match="fuera del periodo"):
        service.save_training_plan(conn, plan)


def test_replan_keeps_past_sessions(conn):
    service.save_training_plan(conn, make_plan())

    plan = service.replan(conn, date(2026, 10, 8), [
        PlannedSession(day=date(2026, 10, 9), session_type="tempo", description="Tempo 20 min"),
    ])

    assert [(s.day, s.session_type) for s in plan.sessions] == [
        (date(2026, 10, 6), "easy"),   # anterior a la fecha: se conserva
        (date(2026, 10, 9), "tempo"),  # nueva
    ]


def test_replan_changes_only_the_given_range(conn):
    service.save_training_plan(conn, make_plan())

    plan = service.replan(conn, date(2026, 10, 7), [
        PlannedSession(day=date(2026, 10, 9), session_type="tempo", description="Tempo 20 min"),
    ], to_day=date(2026, 10, 9))

    assert [(s.day, s.session_type) for s in plan.sessions] == [
        (date(2026, 10, 6), "easy"),   # antes del rango
        (date(2026, 10, 9), "tempo"),  # sustituye a las series del día 8
        (date(2026, 10, 10), "long"),  # después del rango: se conserva
    ]

def test_plan_progress(conn):
    service.save_training_plan(conn, make_plan())
    plan = db.get_active_plan(conn)
    add_run(conn, utc(2026, 10, 6, 17, 0), km=1.2, minutes=8, hr=140)   # calentamiento
    add_run(conn, utc(2026, 10, 6, 17, 15), km=6.1, minutes=35)        # rodaje, sin pulsómetro
    add_run(conn, utc(2026, 10, 7, 17, 0), km=5, minutes=30, hr=150)   # día sin sesión planificada

    progress = analytics.plan_progress(conn, plan, tz=TZ, today=date(2026, 10, 9))

    assert [p.status for p in progress.sessions] == ["done", "missed", "pending"]
    first = progress.sessions[0]
    assert first.runs == 2
    assert first.actual_distance_m == pytest.approx(7300)
    assert first.actual_avg_hr == pytest.approx(140)  # solo cuenta la carrera con pulsómetro
    assert [r.day for r in progress.unplanned_runs] == [date(2026, 10, 7)]


def test_session_status():
    today = date(2026, 10, 8)

    assert analytics.session_status(date(2026, 10, 6), runs=1, today=today) == "done"
    assert analytics.session_status(date(2026, 10, 6), runs=0, today=today) == "missed"
    assert analytics.session_status(today, runs=0, today=today) == "today"
    assert analytics.session_status(date(2026, 10, 10), runs=0, today=today) == "pending"