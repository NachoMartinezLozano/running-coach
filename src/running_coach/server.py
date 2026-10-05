"""Servidor MCP: da a Claude acceso a tus datos de carrera.

Con el transporte stdio, la entrada y la salida estándar son el canal por el que
hablan Claude y el servidor. Por eso aquí nunca se usa print(): cualquier texto
en stdout rompería la comunicación. Los mensajes de diagnóstico van con logging,
que escribe en stderr.
"""
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, time
from typing import Literal
from zoneinfo import ZoneInfo

import psycopg
from mcp.server import MCPServer

from running_coach import db, service
from running_coach.config import timezone_name
from running_coach.metrics import HeartRateZone, format_duration, format_pace, pace_s_per_km, parse_duration
from running_coach.models import SESSION_TYPES, Activity

logger = logging.getLogger(__name__)

mcp = MCPServer("running-coach")


# ---------- Conversión de los datos al formato que lee Claude ----------
# Funciones normales (sin decorador) para poder probarlas sin el protocolo MCP.

WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def _round(value: float | None, digits: int = 1) -> float | None:
    return round(value, digits) if value is not None else None


def _minutes(seconds: float) -> float:
    return round(seconds / 60, 1)


def zone_payload(zone: HeartRateZone) -> dict:
    return {
        "zone": zone.name,
        "min_bpm": round(zone.low_bpm) if zone.low_bpm > 0 else None,
        "max_bpm": round(zone.high_bpm) if zone.high_bpm is not None else None,
    }


def profile_payload(conn: psycopg.Connection) -> dict:
    profile = service.get_profile(conn)
    today = service.today()
    payload = {
        "today": today.isoformat(),
        "goal": profile.goal,
        "goal_date": profile.goal_date.isoformat() if profile.goal_date else None,
        "days_until_goal": (profile.goal_date - today).days if profile.goal_date else None,
        "weekly_days_available": profile.weekly_days,
        "max_hr": profile.max_hr,
        "resting_hr": profile.resting_hr,
        "notes": profile.notes,
    }
    try:
        payload["heart_rate_zones"] = [zone_payload(z) for z in service.heart_rate_zones(conn)]
    except service.ProfileIncompleteError as exc:
        payload["heart_rate_zones"] = None
        payload["missing"] = str(exc)
    return payload


def weekly_summary_payload(conn: psycopg.Connection, weeks: int) -> dict:
    return {
        "weeks": [
            {
                "week_start": w.week_start.isoformat(),
                "in_progress": w.is_current,
                "days_run": w.sessions,
                "activities": w.runs,
                "distance_km": round(w.distance_m / 1000, 2),
                "moving_time": format_duration(w.moving_time_s),
                "pace": format_pace(w.pace_s_per_km) if w.runs else None,
                "longest_run_km": round(w.longest_run_m / 1000, 2),
                "avg_hr": _round(w.avg_hr, 0),
                "activities_with_hr": w.runs_with_hr,
            }
            for w in service.weekly_summary(conn, weeks)
        ],
        "notes": [
            "Semanas de lunes a domingo en hora local; la semana con in_progress=true aún no ha terminado.",
            "days_run cuenta días con carrera: un calentamiento y la carrera del mismo día son una sesión.",
            "avg_hr solo incluye carreras con pulsómetro; null significa sin medir, no cero.",
        ],
    }


def intensity_payload(conn: psycopg.Connection, weeks: int) -> dict:
    dist = service.intensity_distribution(conn, weeks)
    measured = dist.measured_s
    return {
        "weeks": weeks,
        "zones": [
            {
                **zone_payload(zone),
                "minutes": _minutes(seconds),
                "percent": round(100 * seconds / measured) if measured else None,
            }
            for zone, seconds in zip(dist.zones, dist.seconds_in_zone)
        ],
        "unmeasured_minutes": _minutes(dist.unmeasured_s),
        "notes": [
            "Zonas por el método de Karvonen (FC de reserva) si hay FC en reposo; si no, % de la FC máxima.",
            "Aproximación por kilómetro: cada parcial cuenta entero en la zona de su FC media.",
            "Los porcentajes excluyen el tiempo sin pulsómetro (unmeasured_minutes).",
        ],
    }


def _ratio_payload(load, scale: float = 1) -> dict:
    return {
        "last_7_days": round(load.acute / scale, 1),
        "weekly_avg_last_28_days": round(load.chronic / scale, 1),
        "ratio": _round(load.ratio, 2),
    }


def training_load_payload(conn: psycopg.Connection, weeks: int) -> dict:
    report = service.training_load(conn, weeks)
    return {
        "weeks": [
            {
                "week_start": w.week_start.isoformat(),
                "in_progress": w.is_current,
                "distance_km": round(w.distance_m / 1000, 2),
                "load": round(w.trimp),
                "unmeasured_minutes": _minutes(w.unmeasured_s),
            }
            for w in report.weeks
        ],
        "acute_chronic": {
            "distance_km": _ratio_payload(report.distance, scale=1000),
            "load": _ratio_payload(report.trimp),
        },
        "notes": [
            "load es el TRIMP de Edwards: minutos en cada zona multiplicados por el número de la zona (1-5).",
            "El tiempo sin pulsómetro no suma carga.",
            "ratio = últimos 7 días / media semanal de los últimos 28. Orientativo: 0,8-1,3 progresión "
            "habitual, >1,5 subida brusca. Con pocas carreras por semana es muy variable.",
        ],
    }


def recent_runs_payload(conn: psycopg.Connection, weeks: int) -> dict:
    return {
        "runs": [
            {
                "id": r.id,
                "start": r.local_start.strftime("%Y-%m-%d %H:%M"),
                "weekday": WEEKDAYS[r.local_start.weekday()],
                "device": r.device,
                "distance_km": round(r.distance_m / 1000, 2),
                "moving_time": format_duration(r.moving_time_s),
                "pace": format_pace(r.pace_s_per_km),
                "avg_hr": _round(r.avg_hr, 0),
                "max_hr": r.max_hr,
                "elevation_gain_m": _round(r.elevation_gain_m, 0),
                "session_type": r.session_type,
                "rpe": r.rpe,
                "notes": r.notes,
                "km_splits": r.splits,
            }
            for r in service.recent_runs(conn, weeks)
        ],
        "notes": [
            "Horas en la zona horaria local del atleta.",
            "Las carreras con device 'Strava (app móvil)' no tienen pulsaciones.",
        ],
    }

def _local(dt) -> str:
    """Fecha y hora en la zona horaria del atleta, como texto."""
    return dt.astimezone(ZoneInfo(timezone_name())).strftime("%Y-%m-%d %H:%M")


def _saved_run_payload(a: Activity) -> dict:
    return {
        "id": a.id,
        "start": _local(a.start_time),
        "distance_km": round(a.distance_m / 1000, 2),
        "moving_time": format_duration(a.duration_s),
        "pace": format_pace(pace_s_per_km(a.distance_m, a.duration_s)),
        "avg_hr": a.avg_hr,
        "max_hr": a.max_hr,
        "session_type": a.session_type,
        "rpe": a.rpe,
        "notes": a.notes,
    }


def _parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"Fecha no válida: {text!r}. Usa el formato AAAA-MM-DD.") from None


def _parse_time(text: str) -> time:
    try:
        return time.fromisoformat(text)
    except ValueError:
        raise ValueError(f"Hora no válida: {text!r}. Usa el formato HH:MM.") from None


def log_run_payload(conn: psycopg.Connection, *, run_date: str, distance_km: float, duration: str,
                    start_time: str | None = None, avg_hr: float | None = None, max_hr: int | None = None,
                    elevation_gain_m: float | None = None, session_type: str | None = None,
                    rpe: int | None = None, notes: str | None = None, force: bool = False) -> dict:
    """Convierte los datos tal como los da Claude (texto) en tipos de Python y registra la carrera."""
    result = service.log_manual_run(
        conn,
        day=_parse_date(run_date),
        distance_km=distance_km,
        duration_s=parse_duration(duration),
        start=_parse_time(start_time) if start_time else None,
        avg_hr=avg_hr,
        max_hr=max_hr,
        elevation_gain_m=elevation_gain_m,
        session_type=session_type,
        rpe=rpe,
        notes=notes,
        force=force,
    )
    if result.activity is None:
        return {
            "saved": False,
            "reason": "Ese día ya hay una carrera de distancia parecida; probablemente sea la misma.",
            "similar_runs": [
                {"id": r["id"], "start": _local(r["start_time"]), "distance_km": round(r["distance_m"] / 1000, 2)}
                for r in result.similar
            ],
            "next_step": "Pregunta al usuario si es una carrera distinta. Solo si lo confirma, "
                         "vuelve a llamar a log_run con force=true.",
        }
    return {"saved": True, "run": _saved_run_payload(result.activity)}


def delete_run_payload(conn: psycopg.Connection, run_id: int) -> dict:
    deleted = service.delete_run(conn, run_id)
    if deleted is None:
        return {"deleted": False, "reason": f"No existe ninguna carrera con id {run_id}."}
    return {
        "deleted": True,
        "run": {"id": deleted["id"], "start": _local(deleted["start_time"]),
                "distance_km": round(deleted["distance_m"] / 1000, 2)},
    }

# ---------- Herramientas MCP ----------

@contextmanager
def _connection() -> Iterator[psycopg.Connection]:
    """Abre la base de datos y traduce los errores a mensajes que Claude pueda explicar."""
    try:
        conn = db.connect()
    except psycopg.OperationalError as exc:
        logger.exception("No se puede conectar a PostgreSQL")
        raise RuntimeError("No se puede conectar a la base de datos. Pide al usuario que abra "
                           "Docker Desktop y arranque el contenedor con 'docker compose up -d'.") from exc
    try:
        with conn:
            yield conn
    except service.ProfileIncompleteError as exc:
        raise RuntimeError(f"{exc} Pide al usuario su FC máxima y en reposo.") from exc
    except ValueError as exc:
        # Datos no válidos (fecha mal escrita, RPE fuera de rango...): Claude puede corregirlos
        raise ValueError(f"Datos no válidos: {exc}") from exc


@mcp.tool()
def get_athlete_profile() -> dict:
    """Perfil del atleta: fecha de hoy, objetivo y días que faltan, disponibilidad semanal,
    FC máxima y en reposo, zonas de pulsaciones y notas (lesiones, preferencias).
    Consúltalo siempre antes de analizar o planificar."""
    with _connection() as conn:
        return profile_payload(conn)


@mcp.tool()
def get_weekly_summary(weeks: int = 12) -> dict:
    """Resumen por semanas (lunes a domingo): días con carrera, km, tiempo, ritmo medio,
    tirada más larga y FC media. Úsalo para ver el volumen y su evolución."""
    with _connection() as conn:
        return weekly_summary_payload(conn, weeks)


@mcp.tool()
def get_intensity_distribution(weeks: int = 12) -> dict:
    """Tiempo y porcentaje en cada zona de pulsaciones (Z1-Z5) durante las últimas semanas.
    Úsalo para saber cuánto entrenamiento es suave y cuánto intenso."""
    with _connection() as conn:
        return intensity_payload(conn, weeks)


@mcp.tool()
def get_training_load(weeks: int = 8) -> dict:
    """Carga semanal (TRIMP de Edwards) y relación aguda/crónica de carga y kilómetros.
    Úsalo para valorar si un aumento de volumen o intensidad es prudente."""
    with _connection() as conn:
        return training_load_payload(conn, weeks)


@mcp.tool()
def list_recent_runs(weeks: int = 4) -> dict:
    """Carreras de las últimas semanas, de la más reciente a la más antigua: fecha y hora,
    distancia, tiempo, ritmo, pulsaciones, desnivel, tipo de sesión, RPE y notas."""
    with _connection() as conn:
        return recent_runs_payload(conn, weeks)

@mcp.tool()
def log_run(run_date: str, distance_km: float, duration: str, start_time: str | None = None,
            avg_hr: float | None = None, max_hr: int | None = None, elevation_gain_m: float | None = None,
            session_type: Literal[SESSION_TYPES] | None = None, rpe: int | None = None,
            notes: str | None = None, force: bool = False) -> dict:
    """Registra una carrera que el usuario te cuenta en la conversación.

    Args:
        run_date: fecha en formato AAAA-MM-DD. Si el usuario dice "hoy" o "ayer", calcúlala a partir
            del campo "today" de get_athlete_profile.
        distance_km: distancia en kilómetros, p. ej. 7.2.
        duration: tiempo total como "mm:ss" o "h:mm:ss", p. ej. "42:30".
        start_time: hora de inicio "HH:MM", si la sabe.
        avg_hr: frecuencia cardíaca media, si la sabe.
        max_hr: frecuencia cardíaca máxima, si la sabe.
        elevation_gain_m: desnivel positivo en metros, si lo sabe.
        session_type: tipo de sesión, si queda claro por lo que cuenta.
        rpe: esfuerzo percibido de 1 (muy suave) a 10 (máximo).
        notes: sensaciones, molestias, clima... con las palabras del usuario.
        force: guardar aunque ese día ya haya una carrera parecida. Úsalo solo si el usuario
            confirma que es una carrera distinta.

    Necesitas como mínimo la fecha, la distancia y la duración. Si el usuario no menciona la FC media
    ni el RPE, pregúntaselos una vez, porque mejoran mucho el análisis, pero no insistas.
    Antes de guardar, resume los datos que vas a registrar.
    """
    with _connection() as conn:
        return log_run_payload(conn, run_date=run_date, distance_km=distance_km, duration=duration,
                               start_time=start_time, avg_hr=avg_hr, max_hr=max_hr,
                               elevation_gain_m=elevation_gain_m, session_type=session_type,
                               rpe=rpe, notes=notes, force=force)


@mcp.tool()
def delete_run(run_id: int) -> dict:
    """Borra una carrera por su id (lo ves en list_recent_runs). Úsalo solo cuando el usuario
    pida explícitamente borrar o corregir una carrera, y confirma antes cuál es."""
    with _connection() as conn:
        return delete_run_payload(conn, run_id)

def main() -> None:
    logging.basicConfig(level=logging.INFO)  # por defecto escribe en stderr
    mcp.run(transport="stdio")