"""Configuración compartida por todos los tests."""

import psycopg
import pytest

from running_coach import db
from running_coach.config import database_url

TEST_DATABASE = "running_coach_test"


@pytest.fixture
def conn():
    """Conexión a la base de datos de TESTS, vacía al empezar cada test.

    Nunca apunta a la base de datos real: los tests borran todas las filas.
    Si el contenedor no está arrancado, los tests que la usan se saltan.
    """
    try:
        connection = db.connect(database_url(dbname=TEST_DATABASE))
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL de tests no disponible: ¿está arrancado el contenedor?")
    db.init_schema(connection)
    connection.execute("TRUNCATE activities RESTART IDENTITY CASCADE")
    yield connection
    connection.close()