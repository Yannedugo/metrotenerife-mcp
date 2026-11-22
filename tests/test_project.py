"""Coherencia de versión, traducciones y copia vendorizada."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from metrotenerife import __version__

ROOT = Path(__file__).resolve().parents[1]


def _leaf_keys(value: object, prefix: str = "") -> set[str]:
    if isinstance(value, dict):
        keys: set[str] = set()
        for key, item in value.items():
            keys |= _leaf_keys(item, f"{prefix}.{key}" if prefix else key)
        return keys
    return {prefix}


def test_versions_match() -> None:
    manifest = json.loads(
        (ROOT / "custom_components/metrotenerife/manifest.json").read_text(encoding="utf-8")
    )
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    const = (ROOT / "custom_components/metrotenerife/const.py").read_text(encoding="utf-8")
    assert manifest["version"] == __version__ == pyproject["project"]["version"]
    assert f'VERSION = "{__version__}"' in const
    keys = list(manifest)
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])


def test_translations_have_the_same_keys() -> None:
    base = ROOT / "custom_components/metrotenerife"
    strings = json.loads((base / "strings.json").read_text(encoding="utf-8"))
    english = json.loads((base / "translations/en.json").read_text(encoding="utf-8"))
    spanish = json.loads((base / "translations/es.json").read_text(encoding="utf-8"))
    assert _leaf_keys(strings) == _leaf_keys(english) == _leaf_keys(spanish)
    assert "Próximo tranvía" in json.dumps(spanish, ensure_ascii=False)
    assert "Next tram" in json.dumps(english)


def test_vendored_library_matches_source() -> None:
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import sync_vendor

    assert sync_vendor.check() == 0


def test_hacs_structure() -> None:
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import validate_hacs

    assert validate_hacs.check() == 0
