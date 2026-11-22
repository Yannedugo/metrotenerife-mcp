"""Catálogo estático de paradas y líneas, derivado del GTFS oficial."""

from __future__ import annotations

import json
from pathlib import Path

from metrotenerife.models import Direction, Line, Stop
from metrotenerife.text import fold

_CATALOG_PATH = Path(__file__).resolve().parent / "data" / "catalog.json"
_CACHED: Catalog | None = None


class Catalog:
    """Paradas, líneas y búsqueda sin red."""

    def __init__(
        self, stops: tuple[Stop, ...], lines: tuple[Line, ...], attribution: dict[str, object]
    ) -> None:
        self.stops = stops
        self.lines = lines
        self.attribution = attribution
        self._by_code = {stop.code: stop for stop in stops}
        self._by_gtfs = {stop.gtfs_id: stop for stop in stops if stop.gtfs_id}

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> Catalog:
        stops = tuple(
            Stop(
                code=str(item["code"]),
                name=str(item["name"]),
                lat=float(item["lat"]),  # type: ignore[arg-type]
                lon=float(item["lon"]),  # type: ignore[arg-type]
                lines=tuple(int(line) for line in item["lines"]),  # type: ignore[union-attr]
                gtfs_id=str(item["gtfs_id"]) if item.get("gtfs_id") else None,  # type: ignore[union-attr]
                description=str(item["description"]) if item.get("description") else None,  # type: ignore[arg-type]
                wheelchair=bool(item.get("wheelchair", True)),
            )
            for item in payload["stops"]  # type: ignore[union-attr]
        )
        lines: list[Line] = []
        for item in payload["lines"]:  # type: ignore[union-attr]
            directions = tuple(
                Direction(
                    line=int(direction["line"]),
                    direction=int(direction["direction"]),
                    destination_code=str(direction["destination_code"]),
                    destination_name=str(direction["destination_name"]),
                    stop_codes=tuple(str(code) for code in direction["stop_codes"]),
                    segment_seconds=tuple(
                        int(seconds) for seconds in direction.get("segment_seconds") or ()
                    ),
                )
                for direction in item["directions"]  # type: ignore[index]
            )
            lines.append(
                Line(
                    line=int(item["line"]),  # type: ignore[index]
                    code=str(item["code"]),  # type: ignore[index]
                    name=str(item["name"]),  # type: ignore[index]
                    description=str(item["description"]),  # type: ignore[index]
                    directions=directions,
                )
            )
        attribution = dict(payload.get("attribution") or {})  # type: ignore[arg-type]
        return cls(stops=stops, lines=tuple(lines), attribution=attribution)

    def get(self, code: str) -> Stop | None:
        """Devuelve la parada por código de TranvíaOnline o id GTFS."""
        normalized = code.strip().upper()
        return self._by_code.get(normalized) or self._by_gtfs.get(code.strip())

    def search(self, query: str, *, limit: int = 8) -> list[Stop]:
        """Busca paradas sin distinguir tildes ni mayúsculas.

        Orden: código exacto, nombre que empieza por la consulta, el resto de
        coincidencias. Una consulta vacía no devuelve nada.
        """
        folded = fold(query)
        if not folded:
            return []
        ranked: list[tuple[tuple[int, str], Stop]] = []
        for stop in self.stops:
            score = _score(stop, folded)
            if score is not None:
                ranked.append((score, stop))
        ranked.sort(key=lambda item: item[0])
        bounded = max(1, min(limit, len(self.stops)))
        return [stop for _, stop in ranked[:bounded]]

    def line(self, number: int) -> Line | None:
        for item in self.lines:
            if item.line == number:
                return item
        return None

    def direction_of(self, line: int, direction: int) -> Direction | None:
        item = self.line(line)
        if item is None:
            return None
        for route in item.directions:
            if route.direction == direction:
                return route
        return None

    def lines_serving(self, stop_code: str) -> tuple[int, ...]:
        stop = self.get(stop_code)
        return stop.lines if stop else ()


def load_catalog() -> Catalog:
    """Carga el catálogo embebido, una sola vez por proceso."""
    global _CACHED
    if _CACHED is None:
        payload = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        _CACHED = Catalog.from_payload(payload)
    return _CACHED


def _score(stop: Stop, folded_query: str) -> tuple[int, str] | None:
    code = fold(stop.code)
    name = fold(stop.name)
    gtfs = fold(stop.gtfs_id or "")
    if folded_query == code or (gtfs and folded_query == gtfs):
        return (0, name)
    tokens = name.split()
    if name.startswith(folded_query) or any(token.startswith(folded_query) for token in tokens):
        return (1, name)
    if folded_query in name:
        return (2, name)
    query_tokens = folded_query.split()
    if len(query_tokens) > 1 and all(
        any(token.startswith(piece) or piece in token for token in tokens) for piece in query_tokens
    ):
        return (3, name)
    return None
