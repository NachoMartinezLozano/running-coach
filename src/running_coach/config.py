"""Configuración leída del entorno y del archivo .env del proyecto."""

import os

from dotenv import load_dotenv
from psycopg.conninfo import make_conninfo

# Busca el .env subiendo desde la carpeta de este archivo hasta la raíz del proyecto.
# Las variables que ya existan en el entorno tienen prioridad sobre las del archivo.
load_dotenv()


def database_url(dbname: str | None = None) -> str:
    """Cadena de conexión a PostgreSQL.

    Si existe DATABASE_URL (típico al desplegar en la nube), se usa tal cual.
    Si no, se construye con las variables POSTGRES_* del .env. `dbname` permite
    apuntar a otra base de datos del mismo servidor, como la de los tests.
    """
    if dbname is None and os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    return make_conninfo(
        host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname=dbname or _required("POSTGRES_DB"),
        user=_required("POSTGRES_USER"),
        password=_required("POSTGRES_PASSWORD"),
        connect_timeout=5,  # segundos: mejor un error claro que una espera infinita
    )


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable {name}. ¿Has creado el archivo .env a partir de .env.example?")
    return value

def timezone_name() -> str:
    """Zona horaria del atleta: decide qué día y qué semana es cada carrera."""
    return os.environ.get("RUNNING_COACH_TZ", "Europe/Madrid")