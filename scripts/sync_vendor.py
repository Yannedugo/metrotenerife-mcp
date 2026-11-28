#!/usr/bin/env python3
"""Copia la librería dentro de la integración de Home Assistant.

HACS solo instala `custom_components/metrotenerife`. Hasta que el paquete esté
en PyPI, esa copia es la que ejecuta Home Assistant.

La copia vive como subpaquete de la integración
(`custom_components.metrotenerife.vendor.metrotenerife`), así que no hay que
tocar `sys.path` ni se sombrea un `metrotenerife` instalado en el mismo
proceso. Para que funcione bajo ese nombre, los `from metrotenerife... import`
de la librería se reescriben como importaciones relativas al copiar.

    python scripts/sync_vendor.py
    python scripts/sync_vendor.py --check
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "metrotenerife"
DEST = ROOT / "custom_components" / "metrotenerife" / "vendor" / "metrotenerife"

# `from metrotenerife import X` y `from metrotenerife.sub.mod import X`, con la
# sangría que tengan (también dentro de funciones).
_ABSOLUTE_IMPORT = re.compile(r"^(?P<indent>\s*)from metrotenerife(?P<module>\.[\w.]+)? import ")


def _files(base: Path) -> list[Path]:
    if not base.exists():
        return []
    selected: list[Path] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        selected.append(path.relative_to(base))
    return selected


def relativize(source: str) -> str:
    """Convierte las importaciones absolutas de la librería en relativas."""

    def replace(match: re.Match[str]) -> str:
        module = match.group("module") or ""
        return f"{match.group('indent')}from .{module.lstrip('.')} import "

    return "".join(_ABSOLUTE_IMPORT.sub(replace, line) for line in source.splitlines(keepends=True))


def vendored_bytes(relative: Path) -> bytes:
    """Lo que tiene que contener la copia de ese fichero."""
    raw = (SRC / relative).read_bytes()
    if relative.suffix != ".py":
        return raw
    return relativize(raw.decode("utf-8")).encode("utf-8")


def copy() -> None:
    if DEST.exists():
        shutil.rmtree(DEST)
    for relative in _files(SRC):
        target = DEST / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(vendored_bytes(relative))
        shutil.copystat(SRC / relative, target)


def check() -> int:
    problems: list[str] = []
    source_files = _files(SRC)
    if not source_files:
        problems.append("no está src/metrotenerife")
    for relative in source_files:
        destination = DEST / relative
        if not destination.exists() or destination.read_bytes() != vendored_bytes(relative):
            problems.append(f"distinta o ausente: {relative}")
    for relative in _files(DEST):
        if not (SRC / relative).exists():
            problems.append(f"sobra: {relative}")
    if problems:
        print("La copia vendorizada no coincide con src/metrotenerife.")
        for problem in problems:
            print(f"  {problem}")
        print("Ejecuta: python scripts/sync_vendor.py")
        return 1
    print("Copia vendorizada al día.")
    return 0


def main(argv: list[str]) -> None:
    if "--check" in argv:
        raise SystemExit(check())
    copy()
    print(f"Copiado en {DEST}")


if __name__ == "__main__":
    main(sys.argv)
