"""Normalización de texto para búsquedas tolerantes a tildes y mayúsculas."""

from __future__ import annotations

import unicodedata


def fold(text: str) -> str:
    """Minúsculas sin tildes ni diacríticos, con espacios colapsados."""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    collapsed = " ".join(stripped.casefold().split())
    return collapsed
