#!/usr/bin/env python3
"""Comprueba la estructura que HACS exige a una integración.

La action oficial de HACS rechaza los repositorios privados antes de mirar
el código. Este script cubre esas comprobaciones en local y en CI.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "metrotenerife"
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
REQUIRED_MANIFEST = {
    "categories",
    "codeowners",
    "config_flow",
    "documentation",
    "domain",
    "integration_type",
    "iot_class",
    "issue_tracker",
    "name",
    "requirements",
    "version",
}


def check() -> int:
    problems: list[str] = []
    hacs_path = ROOT / "hacs.json"
    try:
        hacs = json.loads(hacs_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        problems.append(f"hacs.json no es un JSON válido: {err}")
        hacs = {}
    if not isinstance(hacs.get("name"), str) or not hacs.get("name"):
        problems.append("hacs.json necesita un name")
    if not VERSION.fullmatch(str(hacs.get("homeassistant", ""))):
        problems.append("hacs.json homeassistant tiene que ser una versión X.Y.Z")
    if hacs.get("render_readme") and not (ROOT / "README.md").is_file():
        problems.append("render_readme está activo y no hay README.md")

    component = ROOT / "custom_components" / DOMAIN
    manifest_path = component / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        problems.append(f"manifest.json no es un JSON válido: {err}")
        manifest = {}
    missing = REQUIRED_MANIFEST - set(manifest)
    if missing:
        problems.append(f"al manifest le faltan claves: {', '.join(sorted(missing))}")
    if manifest.get("domain") != DOMAIN:
        problems.append("el domain del manifest no coincide con la carpeta")
    keys = list(manifest)
    if keys[:2] != ["domain", "name"] or keys[2:] != sorted(keys[2:]):
        problems.append(
            "las claves del manifest tienen que ir domain, name y luego en orden alfabético"
        )
    if manifest.get("config_flow") and not (component / "config_flow.py").is_file():
        problems.append("config_flow está activo y no hay config_flow.py")
    for relative in ("strings.json", "translations/en.json", "translations/es.json"):
        if not (component / relative).is_file():
            problems.append(f"falta {relative}")

    if problems:
        print("La integración no cumple las comprobaciones de HACS.")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print("Estructura de HACS correcta.")
    return 0


def main() -> None:
    raise SystemExit(check())


if __name__ == "__main__":
    main()
