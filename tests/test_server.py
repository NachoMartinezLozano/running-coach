"""Tests de las respuestas del servidor MCP: los datos, sin el protocolo."""

import json
import pytest

from running_coach import db, server, service
from running_coach.server import SessionInput

def test_profile_without_max_hr_says_what_is_missing(conn):
    payload = server.profile_payload(conn)

    assert payload["heart_rate_zones"] is None
    assert "FC máxima" in payload["missing"]


def test_profile_includes_zones(conn):
    db.update_profile(conn, max_hr=190, resting_hr=57)

    payload = server.profile_payload(conn)

    assert [z["max_bpm"] for z in payload["heart_rate_zones"]] == [137, 150, 163, 177, None]


def test_all_payloads_are_valid_json(conn):
    db.update_profile(conn, max_hr=190, resting_hr=57)
    service.log_manual_run(conn, day=service.today(), distance_km=5, duration_s=1800, avg_hr=150)

    payloads = [
        server.profile_payload(conn),
        server.weekly_summary_payload(conn, 4),
        server.intensity_payload(conn, 4),
        server.training_load_payload(conn, 4),
        server.recent_runs_payload(conn, 4),
    ]

    for payload in payloads:
        json.dumps(payload)  # falla si algo no es serializable (una fecha sin convertir, por ejemplo)
    run = server.recent_runs_payload(conn, 4)["runs"][0]
    assert (run["distance_km"], run["pace"]) == (5, "6:00/km")

def test_log_run_saves_the_run(conn):
    payload = server.log_run_payload(conn, run_date="2026-10-04", distance_km=6.1, duration="35:20",
                                     start_time="19:00", avg_hr=152, rpe=5, notes="Rodaje suave")

    assert payload["saved"]
    run = payload["run"]
    assert (run["start"], run["distance_km"], run["pace"], run["rpe"]) == ("2026-10-04 19:00", 6.1, "5:48/km", 5)


def test_log_run_asks_before_saving_a_possible_duplicate(conn):
    server.log_run_payload(conn, run_date="2026-10-04", distance_km=6.1, duration="35:20")

    second = server.log_run_payload(conn, run_date="2026-10-04", distance_km=6.0, duration="35:00")
    forced = server.log_run_payload(conn, run_date="2026-10-04", distance_km=6.0, duration="35:00", force=True)

    assert not second["saved"]
    assert second["similar_runs"][0]["distance_km"] == 6.1
    assert forced["saved"]


def test_log_run_explains_invalid_dates(conn):
    with pytest.raises(ValueError, match="Fecha no válida"):
        server.log_run_payload(conn, run_date="4/10/2026", distance_km=5, duration="30:00")


def test_delete_run(conn):
    run_id = server.log_run_payload(conn, run_date="2026-10-04", distance_km=5, duration="30:00")["run"]["id"]

    assert server.delete_run_payload(conn, run_id)["deleted"]
    assert not server.delete_run_payload(conn, run_id)["deleted"]  # ya no existe

PLAN_SESSIONS = [
    SessionInput(day="2025-01-07", session_type="easy", description="Rodaje suave", distance_km=6, hr_zone=2),
    SessionInput(day="2025-01-09", session_type="intervals", description="6 x 800 m",
                 pace_fast="5:20", pace_slow="5:30/km"),
]


def save_test_plan(conn, name="Plan de prueba", sessions=PLAN_SESSIONS):
    return server.save_plan_payload(conn, name=name, start_date="2025-01-06", end_date="2025-03-01",
                                    sessions=sessions, goal="10 km")


def test_plan_payload_without_plan(conn):
    assert server.plan_payload(conn)["active_plan"] is None


def test_save_and_get_training_plan(conn):
    saved = save_test_plan(conn)

    payload = server.plan_payload(conn)

    json.dumps(payload)
    assert saved["sessions"] == 2 and saved["archived_previous_plan"] is None
    assert payload["active_plan"]["name"] == "Plan de prueba"
    assert payload["sessions"][1]["target"]["pace"] == "5:20-5:30/km"
    assert payload["sessions"][0]["status"] == "missed"  # fechas pasadas sin carreras
    assert payload["summary"]["compliance_percent"] == 0
    assert save_test_plan(conn, name="Otro")["archived_previous_plan"] == "Plan de prueba"


def test_replan_sessions_changes_only_the_range(conn):
    save_test_plan(conn, sessions=PLAN_SESSIONS + [
        SessionInput(day="2025-01-14", session_type="long", description="Tirada larga", distance_km=8),
    ])

    server.replan_payload(conn, from_date="2025-01-08", to_date="2025-01-12", sessions=[
        SessionInput(day="2025-01-10", session_type="tempo", description="Tempo 20 min"),
    ])

    days = [s["day"] for s in server.plan_payload(conn)["sessions"]]
    assert days == ["2025-01-07", "2025-01-10", "2025-01-14"]