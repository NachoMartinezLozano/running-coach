-- Esquema de la base de datos de running-coach.
-- Se puede ejecutar varias veces sin problema: solo crea lo que no existe.

CREATE TABLE IF NOT EXISTS activities (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- De dónde viene y cómo evitar duplicados
    source           TEXT NOT NULL CHECK (source IN ('bulk_export', 'fit_upload', 'manual')),
    source_ref       TEXT NOT NULL UNIQUE,  -- hash del archivo o uuid del registro manual

    sport            TEXT NOT NULL,
    device           TEXT,
    start_time       TIMESTAMPTZ NOT NULL,

    -- Totales
    distance_m       DOUBLE PRECISION NOT NULL CHECK (distance_m >= 0),
    duration_s       DOUBLE PRECISION NOT NULL CHECK (duration_s >= 0),
    moving_time_s    DOUBLE PRECISION CHECK (moving_time_s >= 0),
    avg_hr           REAL CHECK (avg_hr BETWEEN 30 AND 250),
    max_hr           SMALLINT CHECK (max_hr BETWEEN 30 AND 250),
    avg_cadence      REAL CHECK (avg_cadence > 0),
    elevation_gain_m REAL CHECK (elevation_gain_m >= 0),

    -- Lo que aporta el atleta
    session_type     TEXT CHECK (session_type IN
                         ('easy', 'recovery', 'long', 'tempo', 'intervals', 'race', 'warmup', 'other')),
    rpe              SMALLINT CHECK (rpe BETWEEN 1 AND 10),
    notes            TEXT,

    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Casi todas las consultas filtran por fecha ("las últimas 8 semanas")
CREATE INDEX IF NOT EXISTS idx_activities_start_time ON activities (start_time);

CREATE TABLE IF NOT EXISTS splits (
    activity_id        BIGINT NOT NULL REFERENCES activities (id) ON DELETE CASCADE,
    split_index        SMALLINT NOT NULL CHECK (split_index >= 1),
    distance_m         REAL NOT NULL CHECK (distance_m > 0),
    duration_s         REAL NOT NULL CHECK (duration_s > 0),
    avg_hr             REAL,
    elevation_change_m REAL,
    PRIMARY KEY (activity_id, split_index)
);

-- Perfil del atleta. Una sola fila: es una aplicación de un único usuario.
CREATE TABLE IF NOT EXISTS athlete_profile (
    id          BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),  -- solo puede valer TRUE: una fila
    max_hr      SMALLINT CHECK (max_hr BETWEEN 120 AND 230),
    resting_hr  SMALLINT CHECK (resting_hr BETWEEN 30 AND 100),
    sex         TEXT CHECK (sex IN ('male', 'female')),  -- lo usa la fórmula de carga (TRIMP)
    goal        TEXT,                                    -- p. ej. "Media maratón en menos de 2 horas"
    goal_date   DATE,
    weekly_days SMALLINT CHECK (weekly_days BETWEEN 1 AND 7),
    notes       TEXT,                                    -- lesiones, disponibilidad, preferencias...
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Planes de entrenamiento. Como mucho uno activo; los anteriores quedan archivados como historial.
CREATE TABLE IF NOT EXISTS training_plans (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL,
    goal        TEXT,
    start_date  DATE NOT NULL,
    end_date    DATE NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_date >= start_date)
);

-- Índice único parcial: solo afecta a las filas activas, y como la expresión es
-- constante, impide que haya dos a la vez
CREATE UNIQUE INDEX IF NOT EXISTS one_active_plan ON training_plans ((true)) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS planned_sessions (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    plan_id            BIGINT NOT NULL REFERENCES training_plans (id) ON DELETE CASCADE,
    day                DATE NOT NULL,
    session_type       TEXT NOT NULL CHECK (session_type IN
                           ('easy', 'recovery', 'long', 'tempo', 'intervals', 'race', 'warmup', 'other')),
    description        TEXT NOT NULL,                 -- p. ej. "6 x 800 m a ritmo de 10K, 2 min de recuperación"
    target_distance_m  REAL CHECK (target_distance_m > 0),
    target_duration_s  REAL CHECK (target_duration_s > 0),
    target_pace_fast_s REAL CHECK (target_pace_fast_s > 0),  -- rango de ritmo objetivo, en s/km
    target_pace_slow_s REAL CHECK (target_pace_slow_s > 0),
    target_hr_zone     SMALLINT CHECK (target_hr_zone BETWEEN 1 AND 5),
    CHECK (target_pace_fast_s <= target_pace_slow_s)
);
CREATE INDEX IF NOT EXISTS idx_planned_sessions_plan_day ON planned_sessions (plan_id, day);