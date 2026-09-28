"""Utilidades compartidas por todos los importadores."""

import gzip
import hashlib
import math
from pathlib import Path

from running_coach.models import Split, TrackPoint


# Un tramo entre dos puntos se considera pausa si dura más de 10 s
# y en él se avanza a menos de 0,5 m/s (prácticamente parado).
PAUSE_MIN_GAP_S = 10
PAUSE_MAX_SPEED_MS = 0.5


def read_file_bytes(path: Path) -> bytes:
    """Lee un archivo de actividad, descomprimiéndolo si viene en .gz."""
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix.lower() == ".gz" else data


def file_hash(data: bytes) -> str:
    """Huella única del contenido. Dos archivos idénticos tendrán siempre la misma."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def moving_time_series(points: list[TrackPoint]) -> list[float]:
    """Tiempo en movimiento acumulado en cada punto, descontando las pausas.

    Devuelve una lista con un valor por punto: moving[i] son los segundos
    en movimiento desde la salida hasta el punto i.
    """
    moving = [0.0]
    for prev, cur in zip(points, points[1:]):
        dt = (cur.time - prev.time).total_seconds()
        distance = cur.distance_m - prev.distance_m
        is_pause = dt > PAUSE_MIN_GAP_S and distance / dt < PAUSE_MAX_SPEED_MS
        moving.append(moving[-1] + (0.0 if is_pause else dt))
    return moving


def compute_km_splits(points: list[TrackPoint], min_last_split_m: float = 100) -> list[Split]:
    """Divide la actividad en parciales de 1 km usando el tiempo en movimiento.

    El último parcial puede ser más corto; si mide menos de `min_last_split_m`
    se descarta, porque un ritmo calculado sobre pocos metros no es fiable.
    """
    pts = [p for p in points if p.distance_m is not None]
    if len(pts) < 2:
        return []  # sin distancia no hay parciales (p. ej., una sesión de pesas)

    moving = moving_time_series(pts)
    origin = pts[0].distance_m  # la distancia puede no empezar exactamente en 0
    next_km = origin + 1000

    splits: list[Split] = []
    split_start_t = 0.0
    split_start_alt = next((p.altitude_m for p in pts if p.altitude_m is not None), None)
    split_hrs: list[int] = []

    for i in range(1, len(pts)):
        prev, cur = pts[i - 1], pts[i]
        if cur.heart_rate is not None:
            split_hrs.append(cur.heart_rate)

        # "while" y no "if": si hay un hueco grande, un solo tramo puede cruzar varios km
        while cur.distance_m >= next_km:
            fraction = (next_km - prev.distance_m) / (cur.distance_m - prev.distance_m)
            t_km = moving[i - 1] + (moving[i] - moving[i - 1]) * fraction
            alt_km = _interpolate(prev.altitude_m, cur.altitude_m, fraction)

            splits.append(_make_split(len(splits) + 1, 1000.0, t_km - split_start_t,
                                      split_hrs, split_start_alt, alt_km))
            split_start_t, split_start_alt, split_hrs = t_km, alt_km, []
            next_km += 1000

    remaining = pts[-1].distance_m - (next_km - 1000)
    if remaining >= min_last_split_m:
        splits.append(_make_split(len(splits) + 1, remaining, moving[-1] - split_start_t,
                                  split_hrs, split_start_alt, pts[-1].altitude_m))
    return splits


def _interpolate(a: float | None, b: float | None, fraction: float) -> float | None:
    """Valor intermedio entre a y b. Si falta uno de los dos, devuelve el otro."""
    if a is None or b is None:
        return b if a is None else a
    return a + (b - a) * fraction


def _make_split(index, distance, duration, hrs, alt_start, alt_end) -> Split:
    return Split(
        index=index,
        distance_m=round(distance, 1),
        duration_s=round(duration, 1),
        avg_hr=round(sum(hrs) / len(hrs), 1) if hrs else None,
        elevation_change_m=(round(alt_end - alt_start, 1) + 0.0
                    if alt_start is not None and alt_end is not None else None),
    )

def xml_local_name(tag: str) -> str:
    """'{http://www.topografix.com/GPX/1/1}trkpt' -> 'trkpt'"""
    return tag.rsplit("}", 1)[-1]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en metros entre dos coordenadas, sobre la superficie de la Tierra."""
    earth_radius_m = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * earth_radius_m * math.asin(math.sqrt(a))


def fill_distances(points: list[TrackPoint]) -> None:
    """Calcula la distancia acumulada de cada punto a partir de sus coordenadas.

    Modifica los puntos directamente. Los puntos sin coordenadas heredan
    la distancia del último punto que sí las tenía.
    """
    total = 0.0
    last_with_position = None
    for point in points:
        if point.lat is not None and point.lon is not None:
            if last_with_position is not None:
                total += haversine_m(last_with_position.lat, last_with_position.lon, point.lat, point.lon)
            last_with_position = point
        point.distance_m = total


def elevation_gain(altitudes: list[float | None], threshold_m: float = 2.0) -> float | None:
    """Desnivel positivo acumulado, ignorando oscilaciones menores que `threshold_m`."""
    valid = [a for a in altitudes if a is not None]
    if not valid:
        return None
    gain = 0.0
    reference = valid[0]
    for altitude in valid[1:]:
        if altitude - reference >= threshold_m:  # subida real: la sumamos
            gain += altitude - reference
            reference = altitude
        elif reference - altitude >= threshold_m:  # bajada real: nueva referencia
            reference = altitude
    return round(gain, 1)