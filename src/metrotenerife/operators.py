"""Operadores de transporte.

TranvíaOnline es el primero. Otro operador (TITSA, por ejemplo) implementa el
mismo protocolo y se registra, sin cambiar el servidor MCP ni los modelos.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
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
from metrotenerife.forecast import (
    AVISO_PREVISTO,
    Passage,
    load_schedule,
    merge_live,
    resolve_window,
    theoretical_passages,
    wants_live,
)
from metrotenerife.models import (
    Arrival,
    Line,
    Occupancy,
    Stop,
    Vehicle,
    VehiclePosition,
    VehicleSnapshot,
)
from metrotenerife.occupancy import HIGH_CARGA, normalize_carga
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

    async def describe_vehicle(self, number: int) -> VehicleQuery:
        """Estado de un tranvía por el número pintado. Lo viejo no es el estado actual."""

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
            vehicles = [_label_vehicle(vehicle, self.catalog) for vehicle in snapshot.vehicles]
        except MetrotenerifeError:
            vehicles = []
        board, notes = compose_board(
            filtered,
            vehicles,
            self.catalog,
            per_direction=per_direction,
            now=fetched_at,
        )
        return resolved, board, fetched_at, notes

    async def forecast(
        self,
        stop: str,
        *,
        desde: str | None = None,
        hasta: str | None = None,
        minutos: int | None = None,
        line: int | None = None,
        direction: int | None = None,
    ) -> tuple[Stop, list[Passage], datetime, datetime, bool, str]:
        """Pasos previstos y, si la hora está cerca, los que salen de la fuente."""
        resolved = self.resolve_stop(stop)
        now = self._client.now()
        start, end = resolve_window(now=now, desde=desde, hasta=hasta, minutos=minutos)
        passages = theoretical_passages(
            self.catalog,
            resolved.code,
            start=start,
            end=end,
            line=line,
            direction=direction,
            schedule=load_schedule(),
        )
        mixed = False
        note = AVISO_PREVISTO
        if wants_live(start, end, now):
            try:
                _same, arrivals, _fetched, _notes = await self.arrivals(
                    resolved.code, line=line, direction=direction, per_direction=6
                )
                passages = merge_live(passages, arrivals, start=start, end=end)
                mixed = True
            except MetrotenerifeError:
                note += " No se pudo leer TranvíaOnline; solo hay pasos previstos."
        return resolved, passages, start, end, mixed, note

    async def describe_vehicle(self, number: int) -> VehicleQuery:
        """Estado de un tranvía por el número pintado en la unidad.

        Una fila vieja de cargaVehiculo no se presenta como posición actual.
        """
        if number < 1:
            raise ValueError("El número de vehículo tiene que ser un entero positivo.")
        index, occupancy_available = await self._client.occupancy_index()
        position_available = True
        located: list[Vehicle] = []
        try:
            snapshot = await self._client.vehicles()
            located = [_label_vehicle(vehicle, self.catalog) for vehicle in snapshot.vehicles]
            fetched_at = snapshot.fetched_at
        except MetrotenerifeError:
            position_available = False
            fetched_at = datetime.now(UTC)
        return _describe_vehicle(
            number,
            fresh=index.fresh,
            stale=index.stale,
            located=located,
            fetched_at=fetched_at,
            occupancy_available=occupancy_available,
            position_available=position_available,
        )

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
    return replace(
        vehicle,
        next_stop_name=nxt.name if nxt else vehicle.next_stop_name,
        destination_name=destination.name if destination else vehicle.destination_name,
    )


def compose_board(
    arrivals: list[Arrival],
    vehicles: list[Vehicle],
    catalog: Catalog,
    *,
    per_direction: int,
    now: datetime,
) -> tuple[list[Arrival], list[dict[str, object]]]:
    """Llegadas anunciadas, estimación prudente y posición del mismo servicio."""
    labeled = [_label_vehicle(vehicle, catalog) for vehicle in vehicles]
    board, notes = limit_per_direction(
        arrivals, labeled, catalog, per_direction=per_direction, now=now
    )
    by_service = {vehicle.service: vehicle for vehicle in labeled}
    return [attach_sighting(arrival, by_service.get(arrival.service)) for arrival in board], notes


def attach_sighting(arrival: Arrival, vehicle: Vehicle | None) -> Arrival:
    """Copia la posición en vivo del mismo servicio. Sin vehículo, no hay posición."""
    if vehicle is None:
        return arrival
    vehicle_id = arrival.vehicle_id if arrival.vehicle_id is not None else vehicle.vehicle_id
    return replace(
        arrival,
        vehicle_id=vehicle_id,
        position=VehiclePosition(
            lat=vehicle.lat,
            lon=vehicle.lon,
            next_stop_code=vehicle.next_stop_code,
            next_stop_name=vehicle.next_stop_name,
            minutes_to_next=vehicle.minutes_to_next,
            order=vehicle.order,
        ),
    )


@dataclass(frozen=True, slots=True)
class VehicleQuery:
    """Respuesta de buscar un tranvía por el número pintado."""

    number: int
    state: str
    message: str
    fetched_at: datetime
    occupancy_available: bool
    position_available: bool
    service: str | None = None
    vehicle: Vehicle | None = None
    occupancy_raw: int | None = None
    occupancy_percent: int | None = None
    occupancy_high: bool = False
    occupancy_fresh: bool = False
    occupancy_updated_at: datetime | None = None
    stale_updated_at: datetime | None = None


def _describe_vehicle(
    number: int,
    *,
    fresh: dict[str, Occupancy],
    stale: tuple[Occupancy, ...],
    located: list[Vehicle],
    fetched_at: datetime,
    occupancy_available: bool,
    position_available: bool,
) -> VehicleQuery:
    fresh_rows = [row for row in fresh.values() if row.vehicle_id == number]
    fresh_rows.sort(key=lambda row: row.updated_at, reverse=True)
    by_service = {vehicle.service: vehicle for vehicle in located}
    located_by_number = [
        vehicle
        for vehicle in located
        if vehicle.location_vehicle_id == number or vehicle.vehicle_id == number
    ]

    if fresh_rows:
        chosen = next(
            (row for row in fresh_rows if row.service in by_service),
            fresh_rows[0],
        )
        vehicle = by_service.get(chosen.service)
        if vehicle is None:
            message = (
                f"Hay una fila reciente que asocia el vehículo {number} al servicio "
                f"{chosen.service}, pero ese servicio no está en la posición en vivo. "
                "No se puede decir dónde está."
            )
            if not position_available:
                message += " Tampoco se pudo leer la posición."
            return VehicleQuery(
                number=number,
                state="sin_posicion",
                message=message,
                fetched_at=fetched_at,
                occupancy_available=occupancy_available,
                position_available=position_available,
                service=chosen.service,
                occupancy_raw=chosen.raw,
                occupancy_percent=normalize_carga(chosen.raw),
                occupancy_high=chosen.raw >= HIGH_CARGA,
                occupancy_fresh=True,
                occupancy_updated_at=chosen.updated_at,
            )
        return VehicleQuery(
            number=number,
            state="en_servicio",
            message=f"El vehículo {number} circula ahora como servicio {chosen.service}.",
            fetched_at=fetched_at,
            occupancy_available=occupancy_available,
            position_available=position_available,
            service=chosen.service,
            vehicle=vehicle,
            occupancy_raw=chosen.raw,
            occupancy_percent=normalize_carga(chosen.raw),
            occupancy_high=chosen.raw >= HIGH_CARGA,
            occupancy_fresh=True,
            occupancy_updated_at=chosen.updated_at,
        )

    if located_by_number:
        vehicle = located_by_number[0]
        return VehicleQuery(
            number=number,
            state="en_servicio",
            message=(
                f"El vehículo {number} aparece en la posición en vivo como servicio "
                f"{vehicle.service}. La ocupación no es reciente, así que no se muestra."
            ),
            fetched_at=fetched_at,
            occupancy_available=occupancy_available,
            position_available=position_available,
            service=vehicle.service,
            vehicle=vehicle,
        )

    stale_rows = [row for row in stale if row.vehicle_id == number]
    if stale_rows:
        newest = max(stale_rows, key=lambda row: row.updated_at)
        return VehicleQuery(
            number=number,
            state="dato_antiguo",
            message=(
                f"La última fila del vehículo {number} es del "
                f"{newest.updated_at.strftime('%d/%m/%Y %H:%M')} y queda fuera del margen "
                "de frescura. No se usa como estado actual."
            ),
            fetched_at=fetched_at,
            occupancy_available=occupancy_available,
            position_available=position_available,
            stale_updated_at=newest.updated_at,
        )

    if not occupancy_available and not located_by_number:
        message = (
            f"No se pudo leer la ocupación y la posición en vivo no trae el número {number}. "
            "No hay un estado fiable de ese vehículo."
        )
    else:
        message = (
            f"El vehículo {number} no está en la fuente ahora mismo. "
            "O no circula, o TranvíaOnline no publica ese número."
        )
    return VehicleQuery(
        number=number,
        state="desconocido",
        message=message,
        fetched_at=fetched_at,
        occupancy_available=occupancy_available,
        position_available=position_available,
    )
