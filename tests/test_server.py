"""Tests de las respuestas del servidor MCP: los datos, sin el protocolo."""

import json

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