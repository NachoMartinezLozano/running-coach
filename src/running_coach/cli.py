"""Interfaz de línea de comandos: `coach import ...`."""

import argparse
import sys
from datetime import date
from pathlib import Path

import psycopg

from running_coach import db
from running_coach.importers.strava_export import ImportFilters
from running_coach.service import import_strava_export_into_db


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
    return parser


def filters_from_args(args: argparse.Namespace) -> ImportFilters:
    return ImportFilters(
        since=args.since,
        sports=frozenset(args.sport) if args.sport else ImportFilters.sports,
        min_distance_m=args.min_distance,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "import":
        return _run_import(args)
    return 1


def _run_import(args: argparse.Namespace) -> int:
    filters = filters_from_args(args)
    if not (args.export_dir / "activities.csv").exists():
        print(f"No encuentro {args.export_dir / 'activities.csv'}. "
              "¿Es la carpeta descomprimida de la exportación de Strava?", file=sys.stderr)
        return 1

    since = filters.since.isoformat() if filters.since else "el principio"
    print(f"Importando {args.export_dir} (desde {since}; deportes: {', '.join(sorted(filters.sports))})...")
    try:
        with db.connect() as conn:
            summary = import_strava_export_into_db(conn, args.export_dir, filters)
    except psycopg.OperationalError as exc:
        print(f"No se puede conectar a PostgreSQL. ¿Está arrancado el contenedor? "
              f"(docker compose up -d)\nDetalle: {exc}", file=sys.stderr)
        return 1

    skipped = ", ".join(f"{reason}: {n}" for reason, n in summary.skipped.most_common())
    print(f"  Nuevas:       {summary.inserted}")
    print(f"  Ya existían:  {summary.duplicates}")
    print(f"  Descartadas:  {sum(summary.skipped.values())}" + (f"  ({skipped})" if skipped else ""))
    print(f"  Errores:      {len(summary.errors)}")
    for error in summary.errors:
        print(f"    {error}")
    return 1 if summary.errors else 0