"""Cálculos y formatos de running. Funciones puras: sin base de datos ni archivos."""


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