"""Tests del importador de TCX, con archivos TCX generados en el propio test."""

from datetime import datetime, timedelta, timezone

import pytest

from running_coach.importers.tcx_importer import parse_tcx

T0 = datetime(2026, 6, 10, 18, 0, tzinfo=timezone.utc)


def make_tcx(seconds: int = 600, speed_ms: float = 1000 / 300, sport: str = "Run",
             with_distance: bool = True, leading_whitespace: bool = False) -> bytes:
    """Genera un TCX como los del Amazfit: una vuelta y un punto por segundo."""
    points = []
    for s in range(seconds + 1):
        distance = f"<DistanceMeters>{s * speed_ms:.2f}</DistanceMeters>" if with_distance else ""
        time = (T0 + timedelta(seconds=s)).strftime("%Y-%m-%dT%H:%M:%SZ")
        points.append(
            f"<Trackpoint><Time>{time}</Time>"
            f"<Position><LatitudeDegrees>{40 + s * 0.00003:.6f}</LatitudeDegrees>"
            f"<LongitudeDegrees>-3.0</LongitudeDegrees></Position>"
            f"<AltitudeMeters>100.0</AltitudeMeters>{distance}"
            f"<HeartRateBpm><Value>150</Value></HeartRateBpm>"
            f"<Cadence>80</Cadence></Trackpoint>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">'
        f'<Activities><Activity Sport="{sport}"><Id>{T0.isoformat()}</Id>'
        f'<Lap StartTime="{T0.isoformat()}"><TotalTimeSeconds>{seconds}</TotalTimeSeconds>'
        f"<DistanceMeters>{seconds * speed_ms:.1f}</DistanceMeters>"
        f"<Track>{''.join(points)}</Track></Lap>"
        "<Creator><Name>Amazfit Active 2 (Round)</Name></Creator>"
        "</Activity></Activities></TrainingCenterDatabase>"
    )
    return (("\n   " if leading_whitespace else "") + xml).encode("utf-8")


def test_summary_comes_from_the_lap():
    activity = parse_tcx(make_tcx(), source="bulk_export", source_ref="t1")

    assert activity.sport == "running"  # "Run" se traduce al nombre canónico
    assert activity.device == "Amazfit Active 2 (Round)"
    assert activity.distance_m == pytest.approx(2000, abs=1)
    assert activity.moving_time_s == 600
    assert activity.avg_hr == 150
    assert activity.avg_cadence == 160  # 80 zancadas/min -> 160 pasos/min


def test_splits_from_trackpoints():
    activity = parse_tcx(make_tcx(), source="bulk_export", source_ref="t1")

    assert len(activity.splits) == 2
    assert activity.splits[0].duration_s == pytest.approx(300, abs=0.5)


def test_leading_whitespace_is_tolerated():
    activity = parse_tcx(make_tcx(leading_whitespace=True), source="bulk_export", source_ref="t1")

    assert activity.sport == "running"


def test_distance_from_gps_when_points_lack_it():
    # Sin DistanceMeters en los puntos: la distancia de los parciales sale de las coordenadas
    activity = parse_tcx(make_tcx(with_distance=False), source="bulk_export", source_ref="t1")

    assert len(activity.splits) >= 1