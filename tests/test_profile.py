"""Tests del perfil del atleta."""

from datetime import date

import psycopg
import pytest

from running_coach import db


def test_empty_profile(conn):
    profile = db.get_profile(conn)

    assert profile.max_hr is None and profile.goal is None


def test_update_only_changes_given_fields(conn):
    db.update_profile(conn, max_hr=190, goal="Media maratón")

    profile = db.update_profile(conn, resting_hr=52, goal_date=date(2027, 3, 1))

    assert profile.max_hr == 190  # se conserva
    assert profile.goal == "Media maratón"  # se conserva
    assert profile.resting_hr == 52
    assert profile.goal_date == date(2027, 3, 1)


def test_there_is_only_one_profile(conn):
    db.update_profile(conn, max_hr=190)
    db.update_profile(conn, max_hr=188)

    assert conn.execute("SELECT count(*) AS n FROM athlete_profile").fetchone()["n"] == 1
    assert db.get_profile(conn).max_hr == 188


def test_invalid_values_are_rejected(conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        db.update_profile(conn, resting_hr=200)


def test_unknown_field_is_rejected(conn):
    with pytest.raises(ValueError):
        db.update_profile(conn, weight=70)