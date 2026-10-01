"""Casos de uso de la aplicación.

Aquí se combinan los importadores y la base de datos. La CLI, el servidor MCP
y la futura interfaz web llaman a estas funciones en lugar de repetir la lógica.
"""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

from running_coach import db, analytics
from running_coach.config import timezone_name
from running_coach.importers.strava_export import ImportFilters, import_strava_export


@dataclass
class ImportSummary:
    inserted: int = 0
    duplicates: int = 0
    skipped: Counter = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)


def import_strava_export_into_db(conn: psycopg.Connection, export_dir: Path,
                                 filters: ImportFilters) -> ImportSummary:
    """Lee la exportación de Strava y guarda en la base de datos las actividades nuevas."""
    result = import_strava_export(export_dir, filters)
    db.init_schema(conn)
    inserted, duplicates = db.save_activities(conn, result.activities)
    return ImportSummary(inserted=inserted, duplicates=duplicates,
                         skipped=result.skipped, errors=result.errors)

def weekly_summary(conn: psycopg.Connection, weeks: int = 12) -> list[analytics.WeekSummary]:
    """Resumen semanal de las últimas semanas, en la zona horaria del atleta."""
    return analytics.weekly_summary(conn, weeks, tz=timezone_name())