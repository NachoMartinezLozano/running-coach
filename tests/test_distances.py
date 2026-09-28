"""Tests del cálculo de distancias a partir de coordenadas GPS."""

import math
from datetime import datetime, timedelta, timezone

import pytest

from running_coach.importers.common import fill_distances, haversine_m
from running_coach.models import TrackPoint

T0 = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
# Moviéndose hacia el norte, cada grado de latitud mide lo mismo en cualquier parte
METERS_PER_DEGREE_LAT = 6_371_000 * math.pi / 180


def straight_run(seconds: int, speed_ms: float = 3.0, lat0: float = 40.0, lon0: float = -3.0) -> list[TrackPoint]:
    """Simula una carrera en línea recta hacia el norte, un punto por segundo."""
    step = speed_ms / METERS_PER_DEGREE_LAT  # grados de latitud por segundo
    return [TrackPoint(time=T0 + timedelta(seconds=s), lat=lat0 + s * step, lon=lon0)
            for s in range(seconds + 1)]


def test_haversine_one_degree_of_latitude():
    # Un grado de latitud mide unos 111,2 km
    assert haversine_m(40.0, -3.0, 41.0, -3.0) == pytest.approx(111_195, rel=0.001)


def test_straight_line_distance():
    points = straight_run(300)  # 300 s a 3 m/s

    fill_distances(points)

    assert points[0].distance_m == 0
    assert points[-1].distance_m == pytest.approx(900, rel=0.001)


def test_gps_spike_is_ignored():
    points = straight_run(300)
    # A mitad de carrera, el GPS da un punto 100 m hacia el este y vuelve
    meters_per_degree_lon = METERS_PER_DEGREE_LAT * math.cos(math.radians(40.0))
    points[150].lon += 100 / meters_per_degree_lon

    fill_distances(points)

    # Sin el filtro saldrían unos 1100 m (ir y volver del salto)
    assert points[-1].distance_m == pytest.approx(900, rel=0.001)


def test_real_gap_is_counted():
    points = straight_run(300)
    # Perdemos 30 s de señal, pero seguimos corriendo: el tramo va a 3 m/s y debe contar
    del points[101:131]

    fill_distances(points)

    assert points[-1].distance_m == pytest.approx(900, rel=0.001)


def test_points_without_position_keep_last_distance():
    points = straight_run(10)
    points[5].lat = points[5].lon = None

    fill_distances(points)

    assert points[5].distance_m == points[4].distance_m
    assert points[-1].distance_m == pytest.approx(30, rel=0.001)