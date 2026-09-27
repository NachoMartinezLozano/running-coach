"""Utilidades compartidas por todos los importadores."""

import gzip
import hashlib
from pathlib import Path


def read_file_bytes(path: Path) -> bytes:
    """Lee un archivo de actividad, descomprimiéndolo si viene en .gz."""
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix.lower() == ".gz" else data


def file_hash(data: bytes) -> str:
    """Huella única del contenido. Dos archivos idénticos tendrán siempre la misma."""
    return "sha256:" + hashlib.sha256(data).hexdigest()