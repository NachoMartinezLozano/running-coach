"""Tests del registro manual de carreras."""

from datetime import date, datetime, time, timezone

import pytest

from running_coach import analytics
from running_coach.metrics import hr_zones
from running_coach.service import log_manual_run

TZ = "Europe/Madrid"
DAY = date(2026, 10, 1)


def test_manual_run_is_saved_in_utc(conn):
    result = log_manual_run(conn, day=DAY, distance_km=7.2, duration_s=2550, start=time(19, 30),
                            avg_hr=158, rpe=6, session_type="easy", notes="Buenas piernas", tz=TZ)

    row = conn.execute("SELECT * FROM activities WHERE id = %s", (result.activity.id,)).fetchone()
    assert row["start_time"] == datetime(2026, 10, 1, 17, 30, tzinfo=timezone.utc)  # Madrid en verano: UTC+2
    assert row["source"] == "manual"
    assert row["distance_m"] == 7200
    assert (row["rpe"], row["session_type"], row["notes"]) == (6, "easy", "Buenas piernas")


def test_without_time_it_stays_on_the_same_day(conn):
    log_manual_run(conn, day=DAY, distance_km=5, duration_s=1800, tz=TZ)

    local_day = conn.execute("SELECT (start_time AT TIME ZONE %s)::date AS d FROM activities",
                             (TZ,)).fetchone()["d"]
    assert local_day == DAY


def test_possible_duplicate_needs_force(conn):
    log_manual_run(conn, day=DAY, distance_km=7.2, duration_s=2550, tz=TZ)

    blocked = log_manual_run(conn, day=DAY, distance_km=7.0, duration_s=2500, tz=TZ)
    forced = log_manual_run(conn, day=DAY, distance_km=7.0, duration_s=2500, force=True, tz=TZ)

    assert blocked.activity is None and len(blocked.similar) == 1
    assert forced.activity is not None
    assert conn.execute("SELECT count(*) AS n FROM activities").fetchone()["n"] == 2


def test_warmup_and_run_are_not_duplicates(conn):
    log_manual_run(conn, day=DAY, distance_km=1.2, duration_s=480, tz=TZ)

    result = log_manual_run(conn, day=DAY, distance_km=9.9, duration_s=3560, tz=TZ)

    assert result.activity is not None


def test_invalid_values_are_rejected(conn):
    with pytest.raises(ValueError):
        log_manual_run(conn, day=DAY, distance_km=5, duration_s=1800, rpe=11, tz=TZ)
    with pytest.raises(ValueError):
        log_manual_run(conn, day=DAY, distance_km=0, duration_s=1800, tz=TZ)


def test_manual_run_counts_in_heart_rate_zones(conn):
    log_manual_run(conn, day=date(2026, 9, 22), distance_km=5, duration_s=1800, avg_hr=165, tz=TZ)

    result = analytics.intensity_distribution(conn, hr_zones(190, 57), weeks=1, tz=TZ,
                                              today=date(2026, 9, 25))

    assert result.seconds_in_zone[3] == 1800  # 165 ppm: Z4