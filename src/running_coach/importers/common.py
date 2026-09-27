"""Utilidades compartidas por todos los importadores."""

import gzip
import hashlib
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