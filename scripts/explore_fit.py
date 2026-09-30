"""Exploración de un archivo FIT: qué mensajes y campos escribe el reloj.

Uso: uv run python scripts/explore_fit.py [ruta_a_un_archivo.fit o .fit.gz]
Sin argumentos, busca en la exportación la carrera en FIT más reciente.
"""

import csv
import gzip
import io
import sys
from collections import Counter
from pathlib import Path

import fitdecode

EXPORT_DIR = Path("data/strava_export")
PRIVATE_FIELDS = {"position_lat", "position_long", "start_position_lat", "start_position_long",
                  "end_position_lat", "end_position_long"}  # nunca mostramos coordenadas


def find_latest_fit_run() -> Path:
    with open(EXPORT_DIR / "activities.csv", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        col_id = header.index("ID de actividad")
        col_type = header.index("Tipo de actividad")
        col_file = header.index("Nombre del archivo")
        runs = [r for r in reader if r[col_type] == "Carrera" and ".fit" in r[col_file]]
    # Los ID de Strava son crecientes: el mayor es la actividad más reciente
    latest = max(runs, key=lambda r: int(r[col_id]))
    return EXPORT_DIR / latest[col_file]


def read_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix == ".gz" else data


def show(value):
    return "(oculto)" if value is None else value


path = Path(sys.argv[1]) if len(sys.argv) > 1 else find_latest_fit_run()
print(f"Archivo: {path.name}\n")

message_counts = Counter()
first_of_each = {}  # guardamos el primer mensaje de cada tipo para ver sus campos
record_coverage = Counter()  # cuántos records tienen cada campo con un valor real

with fitdecode.FitReader(io.BytesIO(read_bytes(path))) as fit:
    for frame in fit:
        if isinstance(frame, fitdecode.FitDataMessage):
            message_counts[frame.name] += 1
            first_of_each.setdefault(frame.name, frame)
            if frame.name == "record":
                for field in frame.fields:
                    if field.value is not None:
                        record_coverage[field.name] += 1

print("Mensajes en el archivo:")
for name, n in message_counts.most_common():
    print(f"  {n:6}  {name}")

for name in ("file_id", "session", "record"):
    frame = first_of_each.get(name)
    if frame is None:
        print(f"\n[{name}] no aparece en este archivo")
        continue
    print(f"\n[{name}] campos del primer mensaje:")
    for field in frame.fields:
        value = None if field.name in PRIVATE_FIELDS else field.value
        units = f" {field.units}" if field.units else ""
        print(f"  {field.name:<32} {show(value)}{units}")

# Solo recuentos, nunca valores: es seguro compartirlo
total_records = message_counts["record"]
print(f"\n[record] cobertura de campos en los {total_records} registros:")
for name, n in record_coverage.most_common():
    print(f"  {name:<24} {n:6}  ({n / total_records:.0%})")