"""Previsión teórica de pasos, marcada siempre como prevista.

Las frecuencias salen de la tabla pública de Metrotenerife. El tiempo hasta la
parada sale de los minutos entre paradas del catálogo GTFS. No es un horario
oficial: cada franja reparte salidas uniformes desde su hora de inicio.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from metrotenerife.catalog import Catalog
from metrotenerife.models import Arrival, Direction

CANARY = ZoneInfo("Atlantic/Canary")
LIVE_HORIZON = timedelta(minutes=30)
LOOKBACK = timedelta(minutes=90)
DEFAULT_MINUTES = 90
MAX_WINDOW = timedelta(hours=24)
KIND_LIVE = "en_vivo"
KIND_ESTIMATED = "estimado"
KIND_FORECAST = "previsto"

AVISO_PREVISTO = (
    "Previsión teórica con las frecuencias publicadas en "
    "https://metrotenerife.com/recorridos-y-horarios/ y los minutos entre "
    "paradas del catálogo GTFS. No es un horario oficial. Un paso en_vivo lo "
    "anuncia TranvíaOnline; uno estimado sale de la posición del vehículo; "
    "uno previsto es solo el intervalo de la tabla."
)

_PATH = Path(__file__).resolve().parent / "data" / "frecuencias_2026.json"
_CACHED: Schedule | None = None


@dataclass(frozen=True, slots=True)
class Passage:
    """Un paso por la parada, real, estimado o solo previsto."""

    at: datetime
    line: int
    direction: int
    destination_code: str
    destination_name: str
    stop_code: str
    kind: str
    headway_minutes: float | None = None
    travel_seconds: int | None = None
    service: str | None = None


@dataclass(frozen=True, slots=True)
class Schedule:
    """Tabla de intervalos versionada."""

    payload: dict[str, object]
    holidays: frozenset[str]

    def season_of(self, day: date) -> str:
        key = f"{day.month:02d}-{day.day:02d}"
        for season in self.payload["seasons"]:  # type: ignore[union-attr]
            for start, end in season["ranges"]:  # type: ignore[index]
                if start <= key <= end:
                    return str(season["name"])  # type: ignore[index]
        raise ValueError(f"No hay temporada para {day.isoformat()}.")

    def day_kind(self, day: date) -> str:
        """laborable, sabado o domingo_festivo. Un festivo en sábado usa la última."""
        if day.isoformat() in self.holidays or day.weekday() == 6:
            return "domingo_festivo"
        if day.weekday() == 5:
            return "sabado"
        return "laborable"

    def headway(self, moment: datetime, line: int) -> float | None:
        """Minutos entre tranvías en esa hora, o None si la tabla no da servicio."""
        local = moment.astimezone(CANARY)
        kind = self.day_kind(local.date())
        season = self.season_of(local.date())
        for band in self.payload["bands"]:  # type: ignore[union-attr]
            start_hour = int(band["from_hour"])  # type: ignore[index]
            end_hour = int(band["to_hour"])  # type: ignore[index]
            if start_hour <= local.hour < end_hour:
                minutes = band["minutes"]  # type: ignore[index]
                row = minutes[kind]
                if kind == "laborable":
                    row = row[season]
                value = row[line - 1]
                return None if value is None else float(value)
        return None


def load_schedule() -> Schedule:
    """Carga la tabla embebida, una sola vez por proceso."""
    global _CACHED
    if _CACHED is None:
        payload = json.loads(_PATH.read_text(encoding="utf-8"))
        holidays = frozenset(str(day) for day in payload["holidays_2026"])
        _CACHED = Schedule(payload=payload, holidays=holidays)
    return _CACHED


def resolve_window(
    *,
    now: datetime,
    desde: str | None,
    hasta: str | None,
    minutos: int | None,
) -> tuple[datetime, datetime]:
    """Inicio inclusive y fin exclusive, en hora canaria.

    Sin `hasta` ni `minutos`, la ventana dura 90 minutos. No puede pasar de 24 h.
    """
    if hasta is not None and minutos is not None:
        raise ValueError("Indica hasta o minutos, no los dos.")
    start = _parse_moment(desde) if desde else now.astimezone(CANARY)
    if minutos is not None:
        if minutos < 1 or minutos > 24 * 60:
            raise ValueError("minutos tiene que estar entre 1 y 1440.")
        end = start + timedelta(minutes=minutos)
    elif hasta is not None:
        end = _parse_moment(hasta)
    else:
        end = start + timedelta(minutes=DEFAULT_MINUTES)
    if end <= start:
        raise ValueError("El final de la ventana tiene que ser posterior al inicio.")
    if end - start > MAX_WINDOW:
        raise ValueError("La ventana no puede pasar de 24 horas.")
    return start, end


def wants_live(start: datetime, end: datetime, now: datetime) -> bool:
    """True si la consulta se solapa con la próxima media hora."""
    horizon = now.astimezone(CANARY) + LIVE_HORIZON
    return start < horizon and end > now.astimezone(CANARY)


def theoretical_passages(
    catalog: Catalog,
    stop_code: str,
    *,
    start: datetime,
    end: datetime,
    line: int | None = None,
    direction: int | None = None,
    schedule: Schedule | None = None,
) -> list[Passage]:
    """Pasos previstos en [start, end). No consulta la red."""
    table = schedule or load_schedule()
    stop = catalog.get(stop_code)
    if stop is None:
        return []
    lines = (line,) if line is not None else stop.lines
    search_from = (start - LOOKBACK).astimezone(CANARY)
    search_to = end.astimezone(CANARY)
    window_start = start.astimezone(CANARY)
    window_end = end.astimezone(CANARY)
    passages: list[Passage] = []
    for number in lines:
        route_line = catalog.line(number)
        if route_line is None:
            continue
        for route in route_line.directions:
            if direction is not None and route.direction != direction:
                continue
            if stop.code not in route.stop_codes:
                continue
            travel = _travel_seconds(route, stop.code)
            for departure in _departures(table, number, search_from, search_to):
                arrival = departure + timedelta(seconds=travel)
                if window_start <= arrival < window_end:
                    passages.append(
                        Passage(
                            at=arrival,
                            line=number,
                            direction=route.direction,
                            destination_code=route.destination_code,
                            destination_name=route.destination_name,
                            stop_code=stop.code,
                            kind=KIND_FORECAST,
                            headway_minutes=table.headway(departure, number),
                            travel_seconds=travel,
                        )
                    )
    passages.sort(key=lambda item: (item.at, item.line, item.direction))
    return passages


def forecast_attributes(
    catalog: Catalog,
    stop_code: str,
    arrivals: list[Arrival],
    now: datetime,
    *,
    lines: tuple[int, ...] = (),
    direction: int | None = None,
    limit: int = 8,
    horizon_minutes: int = 120,
) -> list[dict[str, object]]:
    """Próximos pasos para un atributo de Home Assistant. Como mucho `limit`."""
    start = now.astimezone(CANARY)
    end = start + timedelta(minutes=horizon_minutes)
    only_line = lines[0] if len(lines) == 1 else None
    passages = theoretical_passages(
        catalog,
        stop_code,
        start=start,
        end=end,
        line=only_line,
        direction=direction,
    )
    if len(lines) > 1:
        allowed = set(lines)
        passages = [item for item in passages if item.line in allowed]
    relevant = [
        arrival
        for arrival in arrivals
        if (not lines or arrival.line in lines)
        and (direction is None or arrival.direction == direction)
    ]
    if wants_live(start, end, now):
        passages = merge_live(passages, relevant, start=start, end=end)
    return [
        {
            "time": item.at.isoformat(),
            "line": item.line,
            "direction": item.direction,
            "destination": item.destination_name,
            "kind": item.kind,
            "headway_minutes": item.headway_minutes,
        }
        for item in passages[:limit]
    ]


def merge_live(
    forecast: list[Passage],
    arrivals: list[Arrival],
    *,
    start: datetime,
    end: datetime,
) -> list[Passage]:
    """Sustituye un previsto cercano por el paso que anuncia la fuente.

    Cada paso real quita como mucho un previsto: el más cercano de su misma
    línea y sentido dentro del margen y, en caso de empate, el anterior. El
    margen es la mitad del intervalo, entre 90 segundos y 4 minutos.
    """
    window_start = start.astimezone(CANARY)
    window_end = end.astimezone(CANARY)
    live: list[Passage] = []
    for arrival in arrivals:
        moment = arrival.estimated_arrival.astimezone(CANARY)
        if not window_start <= moment < window_end:
            continue
        live.append(
            Passage(
                at=moment,
                line=arrival.line,
                direction=arrival.direction,
                destination_code=arrival.destination_code,
                destination_name=arrival.destination_name,
                stop_code=arrival.stop_code,
                kind=KIND_ESTIMATED if arrival.estimated else KIND_LIVE,
                service=arrival.service,
            )
        )
    replaced: set[int] = set()
    for item in live:
        candidates = [
            (abs((passage.at - item.at).total_seconds()), index)
            for index, passage in enumerate(forecast)
            if index not in replaced and _replaces(passage, item)
        ]
        if candidates:
            replaced.add(min(candidates)[1])
    kept = [passage for index, passage in enumerate(forecast) if index not in replaced]
    merged = kept + live
    merged.sort(key=lambda item: (item.at, item.line, item.direction, item.kind))
    return merged


def _replaces(forecast: Passage, live: Passage) -> bool:
    if forecast.line != live.line or forecast.direction != live.direction:
        return False
    headway = (forecast.headway_minutes or 5) * 60
    margin = max(90.0, min(240.0, headway / 2))
    return abs((forecast.at - live.at).total_seconds()) <= margin


def _departures(
    schedule: Schedule, line: int, search_from: datetime, search_to: datetime
) -> list[datetime]:
    found: list[datetime] = []
    day = search_from.date()
    last = search_to.date()
    while day <= last:
        kind = schedule.day_kind(day)
        season = schedule.season_of(day)
        for band in schedule.payload["bands"]:  # type: ignore[union-attr]
            row = band["minutes"][kind]  # type: ignore[index]
            if kind == "laborable":
                row = row[season]
            interval = row[line - 1]
            if interval is None:
                continue
            start_hour = int(band["from_hour"])  # type: ignore[index]
            end_hour = int(band["to_hour"])  # type: ignore[index]
            begin = datetime(day.year, day.month, day.day, start_hour, tzinfo=CANARY)
            finish = begin + timedelta(hours=end_hour - start_hour)
            step = timedelta(seconds=round(float(interval) * 60))
            moment = begin
            while moment < finish:
                if search_from <= moment < search_to:
                    found.append(moment)
                moment += step
        day += timedelta(days=1)
    return found


def _travel_seconds(route: Direction, stop_code: str) -> int:
    index = route.stop_codes.index(stop_code)
    if len(route.segment_seconds) < index:
        return 0
    return sum(route.segment_seconds[:index])


def _parse_moment(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as err:
        raise ValueError(
            "La fecha tiene que ser ISO, por ejemplo 2026-11-23T07:50:00. "
            "Sin zona horaria se interpreta en Canarias."
        ) from err
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CANARY)
    return parsed.astimezone(CANARY)
