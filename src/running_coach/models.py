"""Modelos de dominio: cómo representa el programa una carrera,
independientemente de si viene de un .fit, un .gpx o un registro manual."""

from dataclasses import dataclass, field
from datetime import datetime, date


@dataclass
class TrackPoint:
    """Una muestra de la actividad (normalmente una por segundo)."""

    time: datetime
    distance_m: float | None = None  # distancia acumulada desde la salida
    lat: float | None = None
    lon: float | None = None
    altitude_m: float | None = None
    heart_rate: int | None = None
    cadence: float | None = None


@dataclass
class Split:
    """Parcial de un kilómetro (el último puede ser más corto)."""

    index: int  # 1, 2, 3...
    distance_m: float
    duration_s: float
    avg_hr: float | None = None
    elevation_change_m: float | None = None


@dataclass
class Activity:
    """Una carrera completa, venga de donde venga."""

    # De dónde viene y cómo evitar duplicados
    source: str  # "bulk_export", "fit_upload" o "manual"
    source_ref: str  # identificador único: hash del archivo, o un uuid si es manual

    # Datos obligatorios: sin ellos no hay carrera
    start_time: datetime  # siempre en UTC
    distance_m: float
    duration_s: float  # tiempo total, pausas incluidas

    # Datos que dependen de la fuente (una entrada manual no tendrá todos)
    sport: str = "running"
    device: str | None = None  # con qué se grabó: "Amazfit Active 2 (Round)", "Strava (app móvil)"...
    moving_time_s: float | None = None  # tiempo sin contar las pausas
    avg_hr: float | None = None
    max_hr: float | None = None
    avg_cadence: float | None = None  # pasos por minuto
    elevation_gain_m: float | None = None

    # Datos que aporta el atleta
    session_type: str | None = None  # easy, long, tempo, intervals...
    rpe: int | None = None  # esfuerzo percibido, de 1 a 10
    notes: str | None = None

    splits: list[Split] = field(default_factory=list)
    id: int | None = None  # lo asigna la base de datos al guardarla

@dataclass
class AthleteProfile:
    """Datos del atleta que no salen de las carreras. Todos opcionales."""

    max_hr: int | None = None
    resting_hr: int | None = None
    sex: str | None = None  # "male" o "female"
    goal: str | None = None
    goal_date: date | None = None
    weekly_days: int | None = None  # días a la semana que puede entrenar
    notes: str | None = None
    updated_at: datetime | None = None