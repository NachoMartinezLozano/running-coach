"""Exploración de la exportación de Strava.

No forma parte del paquete: es una herramienta para entender los datos
antes de escribir el importador.
Uso: uv run python scripts/explore_export.py [carpeta_de_la_exportacion]
"""

import csv
import re
import sys
from collections import Counter
from pathlib import Path

export_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/strava_export")

# utf-8-sig: UTF-8 ignorando la marca invisible (BOM) que algunos programas añaden al principio.
# csv.reader devuelve cada fila como una lista, así que las columnas duplicadas no dan problemas.
with open(export_dir / "activities.csv", encoding="utf-8-sig", newline="") as f:
    reader = csv.reader(f)
    header = next(reader)  # la primera fila son los nombres de las columnas
    rows = list(reader)

# .index() devuelve la posición de la PRIMERA columna con ese nombre
col_date = header.index("Fecha de la actividad")
col_type = header.index("Tipo de actividad")
col_file = header.index("Nombre del archivo")


def file_format(filename: str) -> str:
    """'activities/123.fit.gz' -> '.fit.gz'. Si la actividad no tiene archivo, lo indica."""
    if not filename:
        return "(sin archivo)"
    name = Path(filename).name
    return name[name.index("."):]


def year(date_text: str) -> str:
    """Busca un año (20xx) en el texto de la fecha, esté en el formato que esté."""
    match = re.search(r"20\d\d", date_text)
    return match.group() if match else "?"


print(f"Actividades en el CSV: {len(rows)}")

print("\nPor tipo de actividad:")
for activity_type, n in Counter(r[col_type] for r in rows).most_common():
    print(f"  {n:4}  {activity_type}")

print("\nFormato de archivo según el tipo:")
by_type = Counter((r[col_type], file_format(r[col_file])) for r in rows)
for (activity_type, fmt), n in sorted(by_type.items()):
    print(f"  {n:4}  {activity_type:<22} {fmt}")

print("\nFormato de archivo según el año:")
by_year = Counter((year(r[col_date]), file_format(r[col_file])) for r in rows)
for (y, fmt), n in sorted(by_year.items()):
    print(f"  {n:4}  {y}  {fmt}")

# Solo las carreras: es lo que vamos a importar
print("\nCarreras según el año y el formato:")
runs = Counter((year(r[col_date]), file_format(r[col_file])) for r in rows if r[col_type] == "Carrera")
for (y, fmt), n in sorted(runs.items()):
    print(f"  {n:4}  {y}  {fmt}")