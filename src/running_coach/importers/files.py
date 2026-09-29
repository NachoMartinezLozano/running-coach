"""Elige el lector adecuado para cada archivo de actividad según su extensión."""

from pathlib import Path

from running_coach.importers.fit_importer import parse_fit_file
from running_coach.importers.gpx_importer import parse_gpx_file
from running_coach.importers.tcx_importer import parse_tcx_file
from running_coach.models import Activity

# Extensión -> función que lee ese formato
PARSERS = {
    ".fit": parse_fit_file,
    ".gpx": parse_gpx_file,
    ".tcx": parse_tcx_file,
}


def activity_format(path: Path) -> str | None:
    """'123.fit.gz' -> '.fit'. Devuelve None si el formato no está soportado."""
    name = path.name.lower().removesuffix(".gz")
    return next((ext for ext in PARSERS if name.endswith(ext)), None)


def parse_activity_file(path: Path, source: str = "bulk_export") -> Activity:
    """Lee cualquier archivo de actividad soportado (.fit, .gpx o .tcx, comprimido o no)."""
    fmt = activity_format(path)
    if fmt is None:
        raise ValueError(f"Formato no soportado: {path.name}")
    return PARSERS[fmt](path, source)