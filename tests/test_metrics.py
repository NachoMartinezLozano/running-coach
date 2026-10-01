"""Tests de los cálculos y formatos de running."""

from running_coach.metrics import format_duration, format_pace, pace_s_per_km


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