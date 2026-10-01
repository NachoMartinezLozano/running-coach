"""Interfaz de línea de comandos: `coach import` y `coach weeks`."""

import argparse
import sys
from datetime import date
from pathlib import Path

import psycopg

from running_coach import db
from running_coach.importers.strava_export import ImportFilters
from running_coach.metrics import format_duration, format_pace
from running_coach.service import import_strava_export_into_db, weekly_summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coach", description="Analiza tus carreras y planifica entrenamientos.")
    commands = parser.add_subparsers(dest="command", required=True)

    imp = commands.add_parser("import", help="Importa la exportación de Strava a la base de datos")
    imp.add_argument("export_dir", type=Path, help="Carpeta descomprimida de la exportación de Strava")
    imp.add_argument("--since", type=date.fromisoformat, metavar="AAAA-MM-DD",
                     help="Importar solo actividades desde esta fecha")
    imp.add_argument("--sport", action="append", metavar="DEPORTE",
                     help="Deporte a importar (repetible). Por defecto: running")
    imp.add_argument("--min-distance", type=float, default=ImportFilters.min_distance_m, metavar="METROS",
                     help=f"Distancia mínima (por defecto: {ImportFilters.min_distance_m:.0f})")

    weeks = commands.add_parser("weeks", help="Resumen semanal de tus carreras")
    weeks.add_argument("--weeks", type=int, default=12, help="Número de semanas (por defecto: 12)")
    return parser


def filters_from_args(args: argparse.Namespace) -> ImportFilters:
    return ImportFilters(
        since=args.since,
        sports=frozenset(args.sport) if args.sport else ImportFilters.sports,
        min_distance_m=args.min_distance,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "import":
            return _run_import(args)
        if args.command == "weeks":
            return _run_weeks(args)
    except psycopg.OperationalError as exc:
        print(f"No se puede conectar a PostgreSQL. ¿Está arrancado el contenedor? "
              f"(docker compose up -d)\nDetalle: {exc}", file=sys.stderr)
    return 1


def _run_import(args: argparse.Namespace) -> int:
    filters = filters_from_args(args)
    if not (args.export_dir / "activities.csv").exists():
        print(f"No encuentro {args.export_dir / 'activities.csv'}. "
              "¿Es la carpeta descomprimida de la exportación de Strava?", file=sys.stderr)
        return 1

    since = filters.since.isoformat() if filters.since else "el principio"
    print(f"Importando {args.export_dir} (desde {since}; deportes: {', '.join(sorted(filters.sports))})...")
    with db.connect() as conn:
        summary = import_strava_export_into_db(conn, args.export_dir, filters)

    skipped = ", ".join(f"{reason}: {n}" for reason, n in summary.skipped.most_common())
    print(f"  Nuevas:       {summary.inserted}")
    print(f"  Ya existían:  {summary.duplicates}")
    print(f"  Descartadas:  {sum(summary.skipped.values())}" + (f"  ({skipped})" if skipped else ""))
    print(f"  Errores:      {len(summary.errors)}")
    for error in summary.errors:
        print(f"    {error}")
    return 1 if summary.errors else 0


def _run_weeks(args: argparse.Namespace) -> int:
    with db.connect() as conn:
        weeks = weekly_summary(conn, args.weeks)

    print(f"{'Semana':<12}{'Carreras':>9}{'Km':>8}{'Tiempo':>10}{'Ritmo':>11}{'Larga':>8}{'FC':>7}")
    partial_hr = False
    for w in weeks:
        hr = "-" if w.avg_hr is None else f"{w.avg_hr:.0f}"
        if w.avg_hr is not None and w.runs_with_hr < w.runs:
            hr += "*"
            partial_hr = True
        print(f"{w.week_start.isoformat():<12}{w.runs:>9}{w.distance_m / 1000:>8.1f}"
              f"{format_duration(w.moving_time_s):>10}{format_pace(w.pace_s_per_km):>11}"
              f"{w.longest_run_m / 1000:>8.1f}{hr:>7}")
    if partial_hr:
        print("* FC media solo de las carreras con pulsómetro de esa semana")
    return 0