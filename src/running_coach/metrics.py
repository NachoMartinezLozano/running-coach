"""Cálculos y formatos de running. Funciones puras: sin base de datos ni archivos."""

from bisect import bisect_right
from dataclasses import dataclass

# Límites entre zonas, como fracción de la FC de reserva (o de la FC máxima si no hay FC en reposo)
ZONE_THRESHOLDS = (0.60, 0.70, 0.80, 0.90)
ZONE_NAMES = ("Z1 Recuperación", "Z2 Aeróbico suave", "Z3 Tempo", "Z4 Umbral", "Z5 VO2máx")

@dataclass(frozen=True)
class HeartRateZone:
    number: int
    name: str
    low_bpm: float  # incluido
    high_bpm: float | None  # excluido; None en la última zona

def pace_s_per_km(distance_m: float, seconds: float | None) -> float | None:
    """Ritmo en segundos por kilómetro. None si no se puede calcular."""
    if not distance_m or distance_m <= 0 or not seconds:
        return None
    return seconds / (distance_m / 1000)


def format_duration(seconds: float | None) -> str:
    """3725 -> '1:02:05'; 305 -> '5:05'."""
    if seconds is None:
        return "-"
    minutes, s = divmod(round(seconds), 60)
    hours, m = divmod(minutes, 60)
    return f"{hours}:{m:02d}:{s:02d}" if hours else f"{m}:{s:02d}"


def format_pace(seconds_per_km: float | None) -> str:
    """324 -> '5:24/km'."""
    if seconds_per_km is None:
        return "-"
    return f"{format_duration(seconds_per_km)}/km"

def hr_zones(max_hr: int, resting_hr: int | None = None) -> list[HeartRateZone]:
    """Cinco zonas de FC.

    Con FC en reposo usa el método de Karvonen (porcentajes de la FC de reserva);
    sin ella, porcentajes de la FC máxima.
    """
    base = resting_hr or 0
    reserve = max_hr - base
    limits = [base + fraction * reserve for fraction in ZONE_THRESHOLDS]
    lows = [0.0, *limits]
    highs = [*limits, None]
    return [HeartRateZone(i + 1, ZONE_NAMES[i], lows[i], highs[i]) for i in range(len(ZONE_NAMES))]


def zone_index(heart_rate: float, zones: list[HeartRateZone]) -> int:
    """Posición (0 a 4) de la zona a la que pertenece una frecuencia cardíaca."""
    return bisect_right([zone.low_bpm for zone in zones[1:]], heart_rate)