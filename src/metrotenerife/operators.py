"""Operadores de transporte.

TranvíaOnline es el primero. Otro operador (TITSA, por ejemplo) implementa el
mismo protocolo y se registra, sin cambiar el servidor MCP ni los modelos.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol

from metrotenerife.catalog import Catalog, load_catalog
from metrotenerife.client import TranviaOnlineClient, filter_arrivals
from metrotenerife.errors import (
    AmbiguousStopError,
    MetrotenerifeError,
    OperatorNotFoundError,
    StopNotFoundError,
)
from metrotenerife.estimate import limit_per_direction
from metrotenerife.models import Arrival, Line, Stop, Vehicle, VehicleSnapshot
from metrotenerife.text import fold

AVISO_EN_VIVO = (
    "Datos en vivo de TranvíaOnline (fuente no oficial de Metrotenerife). "
    "Pueden cambiar sin aviso y no deben redistribuirse como feed."
)
AVISO_CATALOGO = (
    "Catálogo estático derivado del GTFS del Cabildo Insular de Tenerife / "
    "Metropolitano de Tenerife (CC BY 4.0). El feed de origen está caducado "
    "(vigencia hasta el 15/07/2025) y no incluye horarios en servicio."
)


class TransitOperator(Protocol):
    """Lo que el servidor MCP y, más adelante, otros operadores tienen que ofrecer."""

    id: str
    name: str

    def search_stops(self, query: str, *, limit: int = 8) -> list[Stop]:
        """Busca paradas en el catálogo del operador."""

    def lines(self) -> list[Line]:
        """Líneas y paradas en orden. No son horarios."""

    async def arrivals(
        self,
        stop: str,
        *,
        line: int | None = None,
        direction: int | None = None,
        destination: str | None = None,
        per_direction: int = 3,
    ) -> tuple[Stop, list[Arrival], datetime, list[dict[str, object]]]:
        """Parada, llegadas (hasta N por sentido) y notas si no hubo estimación."""

    async def vehicles(self, *, line: int | None = None) -> VehicleSnapshot:
        """Posición de los vehículos, opcionalmente de una sola línea."""


class OperatorRegistry:
    """Registro en memoria. Añadir un operador es una llamada a `register`."""

    def __init__(self) -> None:
        self._operators: dict[str, TransitOperator] = {}

    def register(self, operator: TransitOperator) -> None:
        self._operators[operator.id] = operator

    def get(self, operator_id: str) -> TransitOperator:
        try:
            return self._operators[operator_id]
        except KeyError as err:
            raise OperatorNotFoundError(operator_id, self.available()) from err

    def available(self) -> list[str]:
        return sorted(self._operators)


class TranviaOperator:
    """Tranvía de Tenerife sobre el catálogo GTFS y TranvíaOnline."""

    id = "tranvia"
    name = "Tranvía de Tenerife"

    def __init__(self, client: TranviaOnlineClient, catalog: Catalog | None = None) -> None:
        self._client = client
        self.catalog = catalog or load_catalog()

    def search_stops(self, query: str, *, limit: int = 8) -> list[Stop]:
        return self.catalog.search(query, limit=limit)

    def lines(self) -> list[Line]:
        return list(self.catalog.lines)

    def resolve_stop(self, query: str) -> Stop:
        """Un código exacto, un nombre único, o un error si hay varias paradas."""
        text = query.strip()
        if not text:
            raise StopNotFoundError(query)
        direct = self.catalog.get(text)
        if direct is not None and (
            fold(text) == fold(direct.code) or fold(text) == fold(direct.gtfs_id or "")
        ):
            return direct
        matches = self.catalog.search(text, limit=25)
        if not matches:
            raise StopNotFoundError(query)
        exact = [
            stop
            for stop in matches
            if fold(stop.name) == fold(text) or fold(stop.code) == fold(text)
        ]
        if len(exact) == 1:
            return exact[0]
        if len(matches) == 1:
            return matches[0]
        raise AmbiguousStopError(query, matches)

    async def arrivals(
        self,
        stop: str,
        *,
        line: int | None = None,
        direction: int | None = None,
        destination: str | None = None,
        per_direction: int = 3,
    ) -> tuple[Stop, list[Arrival], datetime, list[dict[str, object]]]:
        resolved = self.resolve_stop(stop)
        fetched_at = datetime.now(UTC)
        raw = await self._client.panel(resolved.code)
        named = [label_arrival(arrival, self.catalog) for arrival in raw]
        filtered = filter_arrivals(named, line=line, direction=direction, destination=destination)
        try:
            snapshot = await self._client.vehicles()
            vehicles = list(snapshot.vehicles)
        except MetrotenerifeError:
            vehicles = []
        board, notes = limit_per_direction(
            filtered,
            vehicles,
            self.catalog,
            per_direction=per_direction,
            now=fetched_at,
        )
        return resolved, board, fetched_at, notes

    async def vehicles(self, *, line: int | None = None) -> VehicleSnapshot:
        snapshot = await self._client.vehicles()
        labeled = tuple(_label_vehicle(vehicle, self.catalog) for vehicle in snapshot.vehicles)
        if line is not None:
            labeled = tuple(vehicle for vehicle in labeled if vehicle.line == line)
        return VehicleSnapshot(
            vehicles=labeled,
            fetched_at=snapshot.fetched_at,
            occupancy_available=snapshot.occupancy_available,
        )


def label_arrival(arrival: Arrival, catalog: Catalog) -> Arrival:
    """Sustituye el nombre en mayúsculas de la API por el del catálogo, si existe."""
    stop = catalog.get(arrival.stop_code)
    destination = catalog.get(arrival.destination_code)
    if stop is None and destination is None:
        return arrival
    return replace(
        arrival,
        stop_name=stop.name if stop else arrival.stop_name,
        destination_name=destination.name if destination else arrival.destination_name,
    )


def _label_vehicle(vehicle: Vehicle, catalog: Catalog) -> Vehicle:
    nxt = catalog.get(vehicle.next_stop_code)
    destination = catalog.get(vehicle.destination_code)
    if nxt is None and destination is None:
        return vehicle
    return Vehicle(
        service=vehicle.service,
        lat=vehicle.lat,
        lon=vehicle.lon,
        line=vehicle.line,
        direction=vehicle.direction,
        minutes_to_next=vehicle.minutes_to_next,
        next_stop_code=vehicle.next_stop_code,
        next_stop_name=nxt.name if nxt else vehicle.next_stop_name,
        destination_code=vehicle.destination_code,
        destination_name=destination.name if destination else vehicle.destination_name,
        order=vehicle.order,
        occupancy_percent=vehicle.occupancy_percent,
        vehicle_id=vehicle.vehicle_id,
        occupancy_updated_at=vehicle.occupancy_updated_at,
        occupancy_discarded=vehicle.occupancy_discarded,
    )
