"""Tests de la capa de base de datos, contra un PostgreSQL real."""

from datetime import datetime, timezone

import psycopg
import pytest

from running_coach import db
from running_coach.models import Activity, Split


def make_activity(source_ref: str = "sha256:abc", splits: list[Split] | None = None, **fields) -> Activity:
    values = dict(
        source="bulk_export",
        source_ref=source_ref,
        start_time=datetime(2026, 9, 23, 18, 15, tzinfo=timezone.utc),
        distance_m=2000.0,
        duration_s=660.0,
        moving_time_s=650.0,
        avg_hr=150.0,
        max_hr=172,
        device="Amazfit Active 2 (Round)",
    )
    values.update(fields)
    activity = Activity(**values)
    activity.splits = splits if splits is not None else [
        Split(index=1, distance_m=1000, duration_s=330, avg_hr=148.0, elevation_change_m=2.0),
        Split(index=2, distance_m=1000, duration_s=320, avg_hr=152.0, elevation_change_m=-1.5),
    ]
    return activity


def test_insert_activity_with_splits(conn):
    activity = make_activity()

    activity_id = db.insert_activity(conn, activity)

    assert activity_id is not None
    assert activity.id == activity_id
    row = conn.execute("SELECT * FROM activities WHERE id = %s", (activity_id,)).fetchone()
    assert row["distance_m"] == 2000.0
    assert row["device"] == "Amazfit Active 2 (Round)"
    assert row["start_time"] == datetime(2026, 9, 23, 18, 15, tzinfo=timezone.utc)
    splits = conn.execute("SELECT * FROM splits WHERE activity_id = %s ORDER BY split_index",
                          (activity_id,)).fetchall()
    assert [s["duration_s"] for s in splits] == [330, 320]


def test_duplicate_is_ignored(conn):
    db.insert_activity(conn, make_activity())

    assert db.insert_activity(conn, make_activity()) is None
    assert conn.execute("SELECT count(*) AS n FROM activities").fetchone()["n"] == 1


def test_save_activities_counts_new_and_duplicates(conn):
    batch = [make_activity("sha256:1"), make_activity("sha256:2")]
    assert db.save_activities(conn, batch) == (2, 0)

    again = [make_activity("sha256:1"), make_activity("sha256:2"), make_activity("sha256:3")]
    assert db.save_activities(conn, again) == (1, 2)


def test_activity_without_optional_fields(conn):
    # Una carrera del móvil: sin pulsaciones ni cadencia
    activity = make_activity(avg_hr=None, max_hr=None, device="Strava (app móvil)")

    activity_id = db.insert_activity(conn, activity)

    row = conn.execute("SELECT avg_hr, max_hr FROM activities WHERE id = %s", (activity_id,)).fetchone()
    assert row["avg_hr"] is None and row["max_hr"] is None


def test_invalid_split_rolls_back_the_whole_activity(conn):
    # Un parcial con duración 0 viola el CHECK de la tabla splits
    broken = make_activity(splits=[Split(index=1, distance_m=1000, duration_s=0)])

    with pytest.raises(psycopg.errors.CheckViolation):
        db.insert_activity(conn, broken)

    # La transacción se deshizo: tampoco quedó guardada la actividad
    assert conn.execute("SELECT count(*) AS n FROM activities").fetchone()["n"] == 0


def test_deleting_activity_deletes_its_splits(conn):
    activity_id = db.insert_activity(conn, make_activity())

    conn.execute("DELETE FROM activities WHERE id = %s", (activity_id,))

    assert conn.execute("SELECT count(*) AS n FROM splits").fetchone()["n"] == 0