"""Tests de las respuestas del servidor MCP: los datos, sin el protocolo."""

import json
import pytest

from running_coach import db, server, service


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