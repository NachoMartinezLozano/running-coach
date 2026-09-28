"""Tests de la lectura del CSV de Strava, con CSV inventados."""

import pytest

from running_coach.importers.strava_csv import read_activities_csv

# Cabecera real en español, reducida: conserva las columnas duplicadas
SPANISH_CSV = (
    "ID de actividad,Tipo de actividad,Descripción de la actividad,Tiempo transcurrido,Distancia,"
    "Nota privada de actividad,Nombre del archivo,Tiempo transcurrido,Tiempo en movimiento,"
    "Distancia,Desnivel positivo,Esfuerzo Percibido\n"
    '101,Carrera,"Buenas piernas, mucho calor\nfui a tope",1341,"4,03",Molestia en el gemelo,'
    "activities/101.gpx,1341.0,1322.0,4030.5,5.9,6\n"
    "102,Entrenamiento con pesas,,1800,0,,activities/102.fit.gz,1800.0,1800.0,0.0,,\n"
)

ENGLISH_CSV = (
    "Activity ID,Activity Type,Filename,Distance,Moving Time\n"
    "201,Run,activities/201.fit.gz,5000.0,1500\n"
)


def write_csv(tmp_path, content: str):
    path = tmp_path / "activities.csv"
    path.write_text(content, encoding="utf-8")
    return path


def test_spanish_csv_uses_raw_values_of_duplicated_columns(tmp_path):
    records = read_activities_csv(write_csv(tmp_path, SPANISH_CSV))

    run = records[0]
    assert run.activity_id == "101"
    assert run.sport == "running"
    assert run.filename == "activities/101.gpx"
    assert run.distance_m == 4030.5  # la segunda "Distancia", no el "4,03" formateado
    assert run.elapsed_time_s == 1341.0
    assert run.moving_time_s == 1322.0
    assert run.elevation_gain_m == 5.9
    assert run.perceived_exertion == 6


def test_description_and_private_note_become_notes(tmp_path):
    run = read_activities_csv(write_csv(tmp_path, SPANISH_CSV))[0]

    # La descripción tiene una coma y un salto de línea dentro de las comillas
    assert "mucho calor\nfui a tope" in run.notes
    assert "gemelo" in run.notes


def test_empty_cells_become_none(tmp_path):
    gym = read_activities_csv(write_csv(tmp_path, SPANISH_CSV))[1]

    assert gym.sport == "strength"
    assert gym.notes is None
    assert gym.elevation_gain_m is None
    assert gym.perceived_exertion is None


def test_english_csv(tmp_path):
    run = read_activities_csv(write_csv(tmp_path, ENGLISH_CSV))[0]

    assert run.sport == "running"
    assert run.distance_m == 5000.0
    assert run.notes is None  # esa columna no existe en este CSV


def test_unknown_language_gives_clear_error(tmp_path):
    path = write_csv(tmp_path, "Kennung,Typ,Datei\n1,Lauf,a.gpx\n")

    with pytest.raises(ValueError, match="Faltan columnas"):
        read_activities_csv(path)

def test_windows_line_breaks_are_normalized(tmp_path):
    """Bug: con finales de línea de Windows (\\r\\n), las notas conservaban el \\r."""
    path = tmp_path / "activities.csv"
    # write_bytes escribe los bytes tal cual, sin ninguna conversión del sistema
    path.write_bytes(SPANISH_CSV.replace("\n", "\r\n").encode("utf-8"))

    run = read_activities_csv(path)[0]

    assert "\r" not in run.notes
    assert "mucho calor\nfui a tope" in run.notes