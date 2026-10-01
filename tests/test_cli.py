"""Tests de la línea de comandos y del caso de uso de importación."""

from datetime import date, datetime, timezone

from factories import make_export, make_gpx
from running_coach.cli import build_parser, filters_from_args
from running_coach.importers.strava_export import ImportFilters
from running_coach.service import import_strava_export_into_db


def parse(*argv: str):
    return filters_from_args(build_parser().parse_args(["import", "export", *argv]))


def test_import_defaults():
    filters = parse()

    assert filters.since is None
    assert filters.sports == frozenset({"running"})
    assert filters.min_distance_m == 500


def test_import_options():
    filters = parse("--since", "2025-01-01", "--sport", "running", "--sport", "cycling",
                    "--min-distance", "1000")

    assert filters.since == date(2025, 1, 1)
    assert filters.sports == frozenset({"running", "cycling"})
    assert filters.min_distance_m == 1000


def test_import_into_db_twice(conn, tmp_path):
    start = datetime(2025, 6, 10, 18, 0, tzinfo=timezone.utc)
    export = make_export(
        tmp_path,
        ["1,Carrera,,activities/1.gpx,3400.0,1100.0,,", "2,Bicicleta,,activities/2.gpx,9000.0,1800.0,,"],
        {"1.gpx": make_gpx(start, 1200)},
    )

    first = import_strava_export_into_db(conn, export, ImportFilters())
    second = import_strava_export_into_db(conn, export, ImportFilters())

    assert (first.inserted, first.duplicates) == (1, 0)
    assert (second.inserted, second.duplicates) == (0, 1)
    assert first.skipped["otro deporte"] == 1