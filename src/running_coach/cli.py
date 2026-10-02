"""Interfaz de línea de comandos: `coach init-db`, `import`, `weeks` y `profile`."""

import argparse
import sys
from datetime import date
from pathlib import Path

import psycopg

from running_coach import db
from running_coach.importers.strava_export import ImportFilters
from running_coach.metrics import format_duration, format_pace
from running_coach.models import AthleteProfile
from running_coach.service import get_profile, import_strava_export_into_db, update_profile, weekly_summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coach", description="Analiza tus carreras y planifica entrenamientos.")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init-db", help="Crea las tablas que falten en la base de datos")

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

    prof = commands.add_parser("profile", help="Muestra o actualiza tu perfil de atleta")
    prof.add_argument("--max-hr", type=int, metavar="PPM", help="Frecuencia cardíaca máxima (ppm)")
    prof.add_argument("--resting-hr", type=int, metavar="PPM", help="Frecuencia cardíaca en reposo (ppm)")
    prof.add_argument("--sex", choices=["male", "female"], help="Sexo (lo usa el cálculo de carga)")
    prof.add_argument("--goal", metavar="TEXTO", help='Objetivo, p. ej. "Media maratón en menos de 2 horas"')
    prof.add_argument("--goal-date", type=date.fromisoformat, metavar="AAAA-MM-DD", help="Fecha del objetivo")
    prof.add_argument("--days", type=int, dest="weekly_days", metavar="N", help="Días por semana que puedes entrenar")
    prof.add_argument("--notes", metavar="TEXTO", help="Lesiones, disponibilidad, preferencias...")
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
        if args.command == "init-db":
            with db.connect() as conn:
                db.init_schema(conn)
            print("Base de datos lista.")
            return 0
        if args.command == "import":
            return _run_import(args)
        if args.command == "weeks":
            return _run_weeks(args)
        if args.command == "profile":
            return _run_profile(args)
    except psycopg.OperationalError as exc:
        print(f"No se puede conectar a PostgreSQL. ¿Está arrancado el contenedor? "
              f"(docker compose up -d)\nDetalle: {exc}", file=sys.stderr)
    except psycopg.errors.CheckViolation as exc:
        print(f"Valor no válido: {exc.diag.message_primary}", file=sys.stderr)
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


PROFILE_LABELS = {
    "max_hr": "FC máxima",
    "resting_hr": "FC en reposo",
    "sex": "Sexo",
    "goal": "Objetivo",
    "goal_date": "Fecha del objetivo",
    "weekly_days": "Días por semana",
    "notes": "Notas",
}


def _run_profile(args: argparse.Namespace) -> int:
    changes = {name: getattr(args, name) for name in PROFILE_LABELS if getattr(args, name) is not None}
    with db.connect() as conn:
        profile = update_profile(conn, **changes) if changes else get_profile(conn)
    _print_profile(profile)
    return 0


def _print_profile(profile: AthleteProfile) -> None:
    for name, label in PROFILE_LABELS.items():
        value = getattr(profile, name)
        print(f"  {label + ':':<20} {value if value is not None else '(sin configurar)'}")