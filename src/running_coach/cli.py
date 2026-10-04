"""Interfaz de línea de comandos: `coach init-db`, `import`, `weeks` y `profile`."""

import argparse
import sys
from datetime import date
from pathlib import Path
from datetime import date, time

import psycopg

from running_coach import db
from running_coach.importers.strava_export import ImportFilters
from running_coach.metrics import format_duration, format_pace, pace_s_per_km, parse_duration
from running_coach.models import SESSION_TYPES, AthleteProfile
from running_coach.service import (
    ProfileIncompleteError,
    add_activity_file,
    get_profile,
    import_strava_export_into_db,
    intensity_distribution,
    log_manual_run,
    training_load,
    update_profile,
    weekly_summary,
)


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
    zones = commands.add_parser("zones", help="Tiempo en cada zona de pulsaciones")
    zones.add_argument("--weeks", type=int, default=12, help="Número de semanas (por defecto: 12)")
    add = commands.add_parser("add", help="Añade actividades desde archivos .fit, .gpx o .tcx")
    add.add_argument("files", type=Path, nargs="+", metavar="ARCHIVO", help="Uno o varios archivos de actividad")

    log = commands.add_parser("log", help="Registra a mano una carrera")
    log.add_argument("day", type=date.fromisoformat, metavar="FECHA", help="Fecha de la carrera (AAAA-MM-DD)")
    log.add_argument("distance_km", type=float, metavar="KM", help="Distancia en kilómetros, p. ej. 7.2")
    log.add_argument("duration_s", type=duration_arg, metavar="DURACIÓN", help="Tiempo: mm:ss o h:mm:ss")
    log.add_argument("--time", type=time.fromisoformat, dest="start", metavar="HH:MM", help="Hora de inicio")
    log.add_argument("--hr", type=float, dest="avg_hr", metavar="PPM", help="FC media")
    log.add_argument("--max-hr", type=int, metavar="PPM", help="FC máxima")
    log.add_argument("--elevation", type=float, dest="elevation_gain_m", metavar="METROS", help="Desnivel positivo")
    log.add_argument("--type", choices=SESSION_TYPES, dest="session_type", help="Tipo de sesión")
    log.add_argument("--rpe", type=int, choices=range(1, 11), metavar="1-10", help="Esfuerzo percibido (1-10)")
    log.add_argument("--notes", metavar="TEXTO", help="Sensaciones, molestias, clima...")
    log.add_argument("--force", action="store_true", help="Guardar aunque haya una carrera parecida ese día")

    load = commands.add_parser("load", help="Carga de entrenamiento semanal")
    load.add_argument("--weeks", type=int, default=8, help="Número de semanas (por defecto: 8)")

    return parser

def duration_arg(text: str) -> float:
    """Adapta parse_duration a argparse, para que muestre el error como cualquier otro argumento."""
    try:
        return parse_duration(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None

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
        if args.command == "zones":
            return _run_zones(args)
        if args.command == "add":
            return _run_add(args)
        if args.command == "log":
            return _run_log(args)
        if args.command == "load":
            return _run_load(args)
    except psycopg.OperationalError as exc:
        print(f"No se puede conectar a PostgreSQL. ¿Está arrancado el contenedor? "
              f"(docker compose up -d)\nDetalle: {exc}", file=sys.stderr)
    except psycopg.errors.CheckViolation as exc:
        print(f"Valor no válido: {exc.diag.message_primary}", file=sys.stderr)
    except ProfileIncompleteError as exc:
        print(f"{exc} Configúralo con: coach profile --max-hr PPM --resting-hr PPM", file=sys.stderr)
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

    print(f"{'Semana':<12}{'Días':>5}{'Carreras':>9}{'Km':>8}{'Tiempo':>10}{'Ritmo':>11}{'Larga':>8}{'FC':>7}")
    partial_hr = False
    for w in weeks:
        hr = "-" if w.avg_hr is None else f"{w.avg_hr:.0f}"
        if w.avg_hr is not None and w.runs_with_hr < w.runs:
            hr += "*"
            partial_hr = True
        current = "  (en curso)" if w.is_current else ""
        print(f"{w.week_start.isoformat():<12}{w.sessions:>5}{w.runs:>9}{w.distance_m / 1000:>8.1f}"
              f"{format_duration(w.moving_time_s):>10}{format_pace(w.pace_s_per_km):>11}"
              f"{w.longest_run_m / 1000:>8.1f}{hr:>7}{current}")
    if partial_hr:
        print("* FC media solo de las carreras con pulsómetro de esa semana")
    return 0

def _run_zones(args: argparse.Namespace) -> int:
    with db.connect() as conn:
        profile = get_profile(conn)
        distribution = intensity_distribution(conn, args.weeks)

    method = (f"Karvonen: FC máx. {profile.max_hr}, reposo {profile.resting_hr}"
              if profile.resting_hr else f"% de la FC máxima ({profile.max_hr})")
    print(f"Zonas ({method}), últimas {args.weeks} semanas\n")
    print(f"{'Zona':<20}{'Pulsaciones':>14}{'Tiempo':>10}{'%':>6}")
    for zone, seconds in zip(distribution.zones, distribution.seconds_in_zone):
        share = seconds / distribution.measured_s if distribution.measured_s else 0
        print(f"{zone.name:<20}{_zone_range(zone):>14}{format_duration(seconds):>10}{share:>6.0%}")

    if distribution.unmeasured_s:
        print(f"\nSin pulsómetro: {format_duration(distribution.unmeasured_s)} (no incluido en los porcentajes)")
    print("Aproximación por kilómetro: cada parcial cuenta entero en la zona de su FC media.")
    return 0

def _run_add(args: argparse.Namespace) -> int:
    errors = 0
    with db.connect() as conn:
        for path in args.files:
            try:
                activity, activity_id = add_activity_file(conn, path)
            except (OSError, ValueError) as exc:
                print(f"  ERROR    {path.name}: {exc}", file=sys.stderr)
                errors += 1
                continue
            status = "Añadida " if activity_id is not None else "Ya existía"
            print(f"  {status} {activity.start_time.astimezone():%Y-%m-%d %H:%M}  {activity.sport:<10}"
                  f"{activity.distance_m / 1000:6.2f} km  {format_duration(activity.moving_time_s or activity.duration_s)}")
    return 1 if errors else 0

def _run_log(args: argparse.Namespace) -> int:
    fields = {name: value for name, value in vars(args).items() if name != "command"}
    try:
        with db.connect() as conn:
            result = log_manual_run(conn, **fields)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if result.activity is None:
        print(f"No se ha guardado: ese día ya hay {len(result.similar)} carrera(s) de distancia parecida:")
        for run in result.similar:
            print(f"  id {run['id']}: {run['start_time'].astimezone():%Y-%m-%d %H:%M}  {run['distance_m'] / 1000:.2f} km")
        print("Si es otra carrera distinta, repite el comando añadiendo --force.")
        return 1

    a = result.activity
    pace = format_pace(pace_s_per_km(a.distance_m, a.duration_s))
    print(f"Guardada: {a.start_time:%Y-%m-%d %H:%M}  {a.distance_m / 1000:.2f} km  "
          f"{format_duration(a.duration_s)}  {pace}")
    return 0

def _zone_range(zone) -> str:
    if zone.high_bpm is None:
        return f"≥ {zone.low_bpm:.0f}"
    if zone.low_bpm == 0:
        return f"< {zone.high_bpm:.0f}"
    return f"{zone.low_bpm:.0f}-{zone.high_bpm:.0f}"

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

def _run_load(args: argparse.Namespace) -> int:
    with db.connect() as conn:
        report = training_load(conn, args.weeks)

    print(f"Carga de entrenamiento (TRIMP de Edwards), últimas {args.weeks} semanas\n")
    print(f"{'Semana':<12}{'Km':>7}{'Carga':>8}{'Sin FC':>9}")
    for w in report.weeks:
        unmeasured = format_duration(w.unmeasured_s) if w.unmeasured_s else "-"
        current = "  (en curso)" if w.is_current else ""
        print(f"{w.week_start.isoformat():<12}{w.distance_m / 1000:>7.1f}{w.trimp:>8.0f}{unmeasured:>9}{current}")

    print("\nÚltimos 7 días frente a la media semanal de los últimos 28 días:")
    _print_ratio("Kilómetros", report.distance, scale=1000, unit=" km")
    _print_ratio("Carga", report.trimp)
    print("Referencia orientativa: entre 0,8 y 1,3 es una progresión habitual; "
          "por encima de 1,5, una subida brusca.")
    return 0


def _print_ratio(label: str, load, scale: float = 1, unit: str = "") -> None:
    ratio = "-" if load.ratio is None else f"{load.ratio:.2f}"
    print(f"  {label + ':':<12}{load.acute / scale:6.1f}{unit} frente a "
          f"{load.chronic / scale:.1f}{unit}/semana  ->  ratio {ratio}")