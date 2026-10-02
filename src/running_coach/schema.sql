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