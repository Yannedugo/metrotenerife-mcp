"""Pone la librería vendorizada en el path antes de importarla.

Home Assistant solo instala esta carpeta. La librería vive en `vendor/` hasta
que se publique en PyPI. Ver el README.
"""

from __future__ import annotations

import sys
from pathlib import Path

_VENDOR = Path(__file__).resolve().parent / "vendor"


def bootstrap() -> None:
    """Añade `vendor/` al inicio de `sys.path` si todavía no está."""
    vendor = str(_VENDOR)
    if vendor not in sys.path:
        sys.path.insert(0, vendor)
