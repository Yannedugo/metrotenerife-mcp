#!/usr/bin/env python3
"""Copia la librería dentro de la integración de Home Assistant.

HACS solo instala `custom_components/metrotenerife`. Hasta que el paquete esté
en PyPI, esa copia es la que ejecuta Home Assistant.

    python scripts/sync_vendor.py
    python scripts/sync_vendor.py --check
"""

from __future__ import annotations

import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "metrotenerife"
DEST = ROOT / "custom_components" / "metrotenerife" / "vendor" / "metrotenerife"


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


def copy() -> None:
    if DEST.exists():
        shutil.rmtree(DEST)
    for relative in _files(SRC):
        target = DEST / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SRC / relative, target)


def check() -> int:
    problems: list[str] = []
    source_files = _files(SRC)
    if not source_files:
        problems.append("no está src/metrotenerife")
    for relative in source_files:
        destination = DEST / relative
        if not destination.exists() or not filecmp.cmp(SRC / relative, destination, shallow=False):
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
