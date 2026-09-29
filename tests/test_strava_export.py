"""Tests del importador de la exportación completa, con una exportación inventada."""

import math
from datetime import date, datetime, timedelta, timezone

from running_coach.importers.strava_export import ImportFilters, import_strava_export

T0 = datetime(2025, 6, 10, 18, 0, tzinfo=timezone.utc)
METERS_PER_DEGREE_LAT = 6_371_000 * math.pi / 180
FILTERS = ImportFilters(since=date(2025, 1, 1))

HEADER = ("ID de actividad,Tipo de actividad,Descripción de la actividad,Nombre del archivo,"
          "Distancia,Tiempo en movimiento,Desnivel positivo,Esfuerzo Percibido\n")


def make_gpx(start: datetime, seconds: int, speed_ms: float = 3.0) -> str:
    """Un GPX como los de la app de Strava: sin pulsaciones, un punto por segundo hacia el norte."""
    step = speed_ms / METERS_PER_DEGREE_LAT
    points = "".join(
        f'<trkpt lat="{40 + s * step:.7f}" lon="-3.0"><ele>100</ele>'
        f'<time>{(start + timedelta(seconds=s)).strftime("%Y-%m-%dT%H:%M:%SZ")}</time></trkpt>'
        for s in range(seconds + 1)
    )
    return ('<?xml version="1.0"?><gpx creator="StravaGPX" xmlns="http://www.topografix.com/GPX/1/1">'
            f"<trk><type>running</type><trkseg>{points}</trkseg></trk></gpx>")


def make_export(tmp_path, rows: list[str], files: dict[str, str]):
    """Crea una carpeta con la estructura de la exportación de Strava."""
    (tmp_path / "activities").mkdir()
    (tmp_path / "activities.csv").write_bytes((HEADER + "\n".join(rows) + "\n").encode("utf-8"))
    for name, content in files.items():
        (tmp_path / "activities" / name).write_bytes(content.encode("utf-8"))
    return tmp_path


def test_gpx_uses_strava_totals_and_csv_data(tmp_path):
    # Nuestro cálculo daría 3600 m (1200 s a 3 m/s); Strava dice 3400 m
    export = make_export(
        tmp_path,
        ["1,Carrera,Piernas cargadas,activities/1.gpx,3400.0,1100.0,12.0,7"],
        {"1.gpx": make_gpx(T0, 1200)},
    )

    result = import_strava_export(export, FILTERS)

    run = result.activities[0]
    assert run.distance_m == 3400.0
    assert run.moving_time_s == 1100.0
    assert run.elevation_gain_m == 12.0
    assert run.rpe == 7
    assert run.notes == "Piernas cargadas"
    assert run.device == "Strava (app móvil)"
    # Los parciales siguen saliendo de los puntos: 3 km completos + 600 m
    assert len(run.splits) == 4


def test_other_sports_are_skipped_without_reading_the_file(tmp_path):
    # El archivo de la bici ni siquiera existe: si se intentara leer, habría un error
    export = make_export(tmp_path, ["2,Bicicleta,,activities/2.gpx,20000.0,3600.0,,"], {})

    result = import_strava_export(export, FILTERS)

    assert result.activities == []
    assert result.skipped["otro deporte"] == 1
    assert result.errors == []


def test_activities_before_since_are_skipped(tmp_path):
    old = datetime(2024, 5, 1, 18, 0, tzinfo=timezone.utc)
    export = make_export(tmp_path, ["3,Carrera,,activities/3.gpx,3600.0,1200.0,,"],
                         {"3.gpx": make_gpx(old, 1200)})

    result = import_strava_export(export, FILTERS)

    assert result.skipped["anterior a la fecha"] == 1


def test_too_short_activities_are_skipped(tmp_path):
    # Como el reloj arrancado por error: 14 m en 76 s
    export = make_export(tmp_path, ["4,Carrera,,activities/4.gpx,14.0,76.0,,"],
                         {"4.gpx": make_gpx(T0, 76, speed_ms=0.2)})

    result = import_strava_export(export, FILTERS)

    assert result.activities == []
    assert result.skipped["demasiado corta"] == 1


def test_broken_file_is_reported_and_import_continues(tmp_path):
    export = make_export(
        tmp_path,
        ["5,Carrera,,activities/5.gpx,3000.0,900.0,,", "6,Carrera,,activities/6.gpx,3600.0,1200.0,,"],
        {"5.gpx": "esto no es XML", "6.gpx": make_gpx(T0, 1200)},
    )

    result = import_strava_export(export, FILTERS)

    assert len(result.errors) == 1 and "5.gpx" in result.errors[0]
    assert len(result.activities) == 1