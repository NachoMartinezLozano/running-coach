"""Tests de los cálculos y formatos de running."""

from running_coach.metrics import format_duration, format_pace, pace_s_per_km, hr_zones, zone_index, parse_duration
import pytest


def test_pace():
    assert pace_s_per_km(10_000, 3000) == 300
    assert pace_s_per_km(0, 3000) is None  # semana sin carreras: no hay ritmo


def test_format_duration():
    assert format_duration(305) == "5:05"
    assert format_duration(3725) == "1:02:05"
    assert format_duration(None) == "-"


def test_format_pace():
    assert format_pace(324) == "5:24/km"
    assert format_pace(299.6) == "5:00/km"  # se redondea al segundo
    assert format_pace(None) == "-"

def test_karvonen_zones():
    zones = hr_zones(max_hr=190, resting_hr=57)  # FC de reserva: 133

    assert [round(z.low_bpm, 1) for z in zones] == [0, 136.8, 150.1, 163.4, 176.7]
    assert zones[-1].high_bpm is None


def test_zones_without_resting_hr_use_max_hr():
    zones = hr_zones(max_hr=190)

    assert [round(z.low_bpm) for z in zones] == [0, 114, 133, 152, 171]


def test_zone_index():
    zones = hr_zones(max_hr=190, resting_hr=57)

    assert zone_index(120, zones) == 0  # Z1
    assert zone_index(145, zones) == 1  # Z2
    assert zone_index(165, zones) == 3  # Z4
    assert zone_index(200, zones) == 4  # por encima del máximo: sigue siendo Z5
    assert zone_index(zones[1].low_bpm, zones) == 1  # el límite inferior pertenece a la zona

def test_parse_duration():
    assert parse_duration("42:30") == 2550
    assert parse_duration("1:02:05") == 3725
    assert parse_duration("45") == 2700  # solo minutos
    for bad in ("abc", "42:75", "-5", "0", "1:2:3:4"):
        with pytest.raises(ValueError):
            parse_duration(bad)