"""Tests del cálculo de parciales por kilómetro."""

import math
from datetime import datetime, timedelta, timezone

import pytest

from running_coach.importers.common import compute_km_splits
from running_coach.models import TrackPoint

T0 = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)


def run_points(km: float, pace_s_per_km: float, hr: int = 150, altitude: float = 100.0) -> list[TrackPoint]:
    """Simula una carrera a ritmo constante con un punto por segundo."""
    speed = 1000 / pace_s_per_km  # metros por segundo
    seconds = int(km * pace_s_per_km)
    return [
        TrackPoint(time=T0 + timedelta(seconds=s), distance_m=s * speed, heart_rate=hr, altitude_m=altitude)
        for s in range(seconds + 1)
    ]


# ---------- Casos básicos ----------

def test_steady_pace_gives_equal_splits():
    points = run_points(km=5, pace_s_per_km=300)

    splits = compute_km_splits(points)

    assert len(splits) == 5
    for split in splits:
        assert split.distance_m == 1000
        assert split.duration_s == pytest.approx(300, abs=0.5)
        assert split.avg_hr == 150


def test_partial_last_split_is_kept():
    splits = compute_km_splits(run_points(km=3.5, pace_s_per_km=300))

    assert len(splits) == 4
    assert splits[-1].distance_m == pytest.approx(500, abs=1)
    assert splits[-1].duration_s == pytest.approx(150, abs=1)


def test_very_short_last_split_is_dropped():
    splits = compute_km_splits(run_points(km=2.05, pace_s_per_km=300))

    assert len(splits) == 2  # los últimos 50 m no llegan al mínimo de 100 m


def test_no_distance_means_no_splits():
    points = [TrackPoint(time=T0 + timedelta(seconds=s), heart_rate=100) for s in range(600)]

    assert compute_km_splits(points) == []  # p. ej., una sesión de pesas


# ---------- Pausas ----------

def test_pause_is_not_counted():
    points = run_points(km=2, pace_s_per_km=300)
    # Simulamos 60 s parados en un semáforo a mitad del segundo kilómetro:
    # el reloj deja de grabar, así que todos los puntos siguientes se retrasan
    for p in points[451:]:
        p.time += timedelta(seconds=60)

    splits = compute_km_splits(points)

    assert splits[1].duration_s == pytest.approx(300, abs=1.5)  # no 360


def test_gps_gap_while_running_is_counted():
    points = run_points(km=2, pace_s_per_km=300)
    # Perdemos 20 s de señal GPS, pero seguimos corriendo: la distancia avanza
    del points[451:470]

    splits = compute_km_splits(points)

    assert splits[1].duration_s == pytest.approx(300, abs=0.5)


# ---------- Regresiones: bugs encontrados con datos reales ----------

def test_first_point_without_altitude():
    """Bug: el reloj no tiene altitud en el primer segundo y el primer parcial salía sin desnivel."""
    points = run_points(km=1, pace_s_per_km=300)
    for s, p in enumerate(points):
        p.altitude_m = 100 + s * 0.01  # subimos 3 m en 300 s
    points[0].altitude_m = None

    splits = compute_km_splits(points)

    assert splits[0].elevation_change_m == pytest.approx(3.0, abs=0.05)


def test_tiny_descent_is_not_negative_zero():
    """Bug: un desnivel de -0,03 m se redondeaba a -0.0."""
    points = run_points(km=1, pace_s_per_km=300)
    for s, p in enumerate(points):
        p.altitude_m = 100 - s * 0.0001  # bajamos solo 3 cm

    splits = compute_km_splits(points)

    # Ojo: -0.0 == 0.0 es True en Python, así que comprobamos el signo explícitamente
    assert math.copysign(1, splits[0].elevation_change_m) == 1