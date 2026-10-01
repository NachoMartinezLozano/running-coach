"""Generadores de datos de prueba compartidos por varios archivos de tests."""

import math
from datetime import datetime, timedelta

METERS_PER_DEGREE_LAT = 6_371_000 * math.pi / 180

STRAVA_CSV_HEADER = ("ID de actividad,Tipo de actividad,Descripción de la actividad,Nombre del archivo,"
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


def make_export(folder, rows: list[str], files: dict[str, str]):
    """Crea una carpeta con la estructura de la exportación de Strava."""
    (folder / "activities").mkdir()
    (folder / "activities.csv").write_bytes((STRAVA_CSV_HEADER + "\n".join(rows) + "\n").encode("utf-8"))
    for name, content in files.items():
        (folder / "activities" / name).write_bytes(content.encode("utf-8"))
    return folder