"""Tercer tranvía por sentido, estimado y nunca inventado.

La API anuncia dos llegadas por parada, línea y sentido. Un tercero solo se
añade si hay un vehículo aguas arriba, en el mismo sentido y con el mismo
destino, y los minutos entre paradas salen del GTFS. Si tendría que dar la
vuelta en la cabecera, no se estima.
"""

from __future__ import annotations

import math
from datetime import datetime

from metrotenerife.catalog import Catalog
from metrotenerife.models import Arrival, Direction, Vehicle

ESTIMATE_ORIGIN = "estimado"
OFFICIAL_ORIGIN = "tranviaonline"
UNAVAILABLE_REASON = (
    "No hay un tranvía aguas arriba cuya llegada se pueda estimar "
    "sin suponer una vuelta en cabecera."
)


def limit_per_direction(
    arrivals: list[Arrival],
    vehicles: list[Vehicle],
    catalog: Catalog,
    *,
    per_direction: int,
    now: datetime,
) -> tuple[list[Arrival], list[dict[str, object]]]:
    """Deja como mucho `per_direction` llegadas por línea, sentido y destino.

    Las anunciadas por TranvíaOnline van primero. El hueco se rellena con
    estimaciones fiables. Si no las hay, la lista se queda más corta.
    """
    per_direction = max(1, per_direction)
    groups: dict[tuple[int, int, str], list[Arrival]] = {}
    for arrival in arrivals:
        if arrival.estimated:
            continue
        key = (arrival.line, arrival.direction, arrival.destination_code)
        groups.setdefault(key, []).append(arrival)

    selected: list[Arrival] = []
    notes: list[dict[str, object]] = []
    for key, official in groups.items():
        ordered = sorted(official, key=lambda item: (item.minutes, item.service))
        chosen = ordered[:per_direction]
        missing = per_direction - len(chosen)
        if missing > 0:
            extras = _estimate(key, ordered, vehicles, catalog, now, missing)
            chosen.extend(extras)
            if len(extras) < missing:
                notes.append(
                    {
                        "linea": key[0],
                        "sentido": key[1],
                        "destino_codigo": key[2],
                        "motivo": UNAVAILABLE_REASON,
                    }
                )
        selected.extend(chosen)
    selected.sort(key=lambda item: (item.line, item.direction, item.minutes, item.estimated))
    return selected, notes


def _estimate(
    key: tuple[int, int, str],
    official: list[Arrival],
    vehicles: list[Vehicle],
    catalog: Catalog,
    now: datetime,
    limit: int,
) -> list[Arrival]:
    line, direction, destination = key
    route = catalog.direction_of(line, direction)
    if route is None or route.destination_code != destination:
        return []
    if len(route.segment_seconds) != len(route.stop_codes) - 1 or not route.stop_codes:
        return []
    stop_code = official[0].stop_code
    try:
        target = route.stop_codes.index(stop_code)
    except ValueError:
        return []

    taken = {arrival.service for arrival in official}
    latest_official = official[-1].minutes if official else -1
    ranked: list[tuple[int, Vehicle]] = []
    for vehicle in vehicles:
        minutes = _minutes_until(vehicle, route, target, taken)
        if minutes is None or minutes <= latest_official:
            continue
        ranked.append((minutes, vehicle))
        taken.add(vehicle.service)
    ranked.sort(key=lambda item: (item[0], item[1].service))

    estimates: list[Arrival] = []
    for minutes, vehicle in ranked[:limit]:
        estimates.append(
            Arrival(
                service=vehicle.service,
                stop_code=stop_code,
                stop_name=official[0].stop_name,
                destination_code=destination,
                destination_name=official[0].destination_name,
                line=line,
                direction=direction,
                minutes=minutes,
                updated_at=now,
                order=vehicle.order,
                approximate=True,
                estimated=True,
                origin=ESTIMATE_ORIGIN,
                occupancy_percent=vehicle.occupancy_percent,
                occupancy_raw=vehicle.occupancy_raw,
                occupancy_fresh=vehicle.occupancy_percent is not None,
                occupancy_high=vehicle.occupancy_high,
                occupancy_updated_at=vehicle.occupancy_updated_at,
                vehicle_id=vehicle.vehicle_id,
                occupancy_discarded=vehicle.occupancy_discarded,
            )
        )
    return estimates


def _minutes_until(
    vehicle: Vehicle,
    route: Direction,
    target: int,
    taken: set[str],
) -> int | None:
    """Minutos hasta la parada, o None si habría que suponer un cambio de sentido."""
    if vehicle.line != route.line or vehicle.direction != route.direction:
        return None
    if vehicle.service in taken or not vehicle.service:
        return None
    if vehicle.destination_code != route.destination_code:
        return None
    try:
        nxt = route.stop_codes.index(vehicle.next_stop_code)
    except ValueError:
        return None
    if nxt > target:
        return None
    seconds = max(0, vehicle.minutes_to_next) * 60
    if nxt < target:
        seconds += sum(route.segment_seconds[nxt:target])
    if seconds < 0:
        return None
    return math.ceil(seconds / 60)
