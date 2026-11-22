"""Modelos de transporte, independientes del operador.

Los nombres de campo están en inglés (código). Los textos que ve una persona
se generan en la capa MCP o en la integración de Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class Stop:
    """Parada de un operador."""

    code: str
    name: str
    lat: float
    lon: float
    lines: tuple[int, ...]
    gtfs_id: str | None = None
    description: str | None = None
    wheelchair: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "name": self.name,
            "lat": self.lat,
            "lon": self.lon,
            "lines": list(self.lines),
            "gtfs_id": self.gtfs_id,
            "description": self.description,
            "wheelchair": self.wheelchair,
        }


@dataclass(frozen=True, slots=True)
class Direction:
    """Un sentido de una línea, con las paradas en orden de marcha."""

    line: int
    direction: int
    destination_code: str
    destination_name: str
    stop_codes: tuple[str, ...]
    segment_seconds: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "line": self.line,
            "direction": self.direction,
            "destination_code": self.destination_code,
            "destination_name": self.destination_name,
            "stop_codes": list(self.stop_codes),
            "segment_seconds": list(self.segment_seconds),
        }


@dataclass(frozen=True, slots=True)
class Line:
    """Línea y sus sentidos."""

    line: int
    code: str
    name: str
    description: str
    directions: tuple[Direction, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "line": self.line,
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "directions": [direction.to_dict() for direction in self.directions],
        }


@dataclass(frozen=True, slots=True)
class VehiclePosition:
    """Dónde está ahora el servicio, si vehicleLocation lo trae en esta consulta."""

    lat: float
    lon: float
    next_stop_code: str
    next_stop_name: str
    minutes_to_next: int
    order: int | None = None


@dataclass(frozen=True, slots=True)
class Arrival:
    """Un tranvía anunciado en una parada."""

    service: str
    stop_code: str
    stop_name: str
    destination_code: str
    destination_name: str
    line: int
    direction: int
    minutes: int
    updated_at: datetime
    order: int | None = None
    approximate: bool = False
    occupancy_percent: int | None = None
    occupancy_raw: int | None = None
    occupancy_fresh: bool = False
    occupancy_high: bool = False
    occupancy_updated_at: datetime | None = None
    vehicle_id: int | None = None
    occupancy_discarded: bool = False
    estimated: bool = False
    origin: str = "tranviaonline"
    position: VehiclePosition | None = None

    @property
    def estimated_arrival(self) -> datetime:
        """Hora estimada de llegada a partir de la última actualización de la fuente."""
        return self.updated_at + timedelta(minutes=self.minutes)

    def to_dict(self) -> dict[str, object]:
        return {
            "service": self.service,
            "stop_code": self.stop_code,
            "stop_name": self.stop_name,
            "destination_code": self.destination_code,
            "destination_name": self.destination_name,
            "line": self.line,
            "direction": self.direction,
            "minutes": self.minutes,
            "updated_at": self.updated_at.isoformat(),
            "estimated_arrival": self.estimated_arrival.isoformat(),
            "order": self.order,
            "approximate": self.approximate,
            "occupancy_percent": self.occupancy_percent,
            "occupancy_raw": self.occupancy_raw,
            "occupancy_fresh": self.occupancy_fresh,
            "occupancy_high": self.occupancy_high,
            "estimated": self.estimated,
            "origin": self.origin,
            "occupancy_updated_at": (
                self.occupancy_updated_at.isoformat() if self.occupancy_updated_at else None
            ),
            "vehicle_id": self.vehicle_id,
            "occupancy_discarded": self.occupancy_discarded,
            "position": None
            if self.position is None
            else {
                "lat": self.position.lat,
                "lon": self.position.lon,
                "next_stop_code": self.position.next_stop_code,
                "next_stop_name": self.position.next_stop_name,
                "minutes_to_next": self.position.minutes_to_next,
                "order": self.position.order,
            },
        }


@dataclass(frozen=True, slots=True)
class Occupancy:
    """Ocupación reciente de un servicio."""

    service: str
    raw: int
    updated_at: datetime
    vehicle_id: int | None = None


@dataclass(frozen=True, slots=True)
class Vehicle:
    """Posición de una unidad y, si es reciente, su ocupación."""

    service: str
    lat: float
    lon: float
    line: int
    direction: int
    minutes_to_next: int
    next_stop_code: str
    next_stop_name: str
    destination_code: str
    destination_name: str
    order: int | None = None
    occupancy_percent: int | None = None
    occupancy_raw: int | None = None
    occupancy_high: bool = False
    vehicle_id: int | None = None
    occupancy_updated_at: datetime | None = None
    occupancy_discarded: bool = False
    location_vehicle_id: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "service": self.service,
            "lat": self.lat,
            "lon": self.lon,
            "line": self.line,
            "direction": self.direction,
            "minutes_to_next": self.minutes_to_next,
            "next_stop_code": self.next_stop_code,
            "next_stop_name": self.next_stop_name,
            "destination_code": self.destination_code,
            "destination_name": self.destination_name,
            "order": self.order,
            "occupancy_percent": self.occupancy_percent,
            "occupancy_raw": self.occupancy_raw,
            "occupancy_high": self.occupancy_high,
            "vehicle_id": self.vehicle_id,
            "location_vehicle_id": self.location_vehicle_id,
            "occupancy_updated_at": (
                self.occupancy_updated_at.isoformat() if self.occupancy_updated_at else None
            ),
            "occupancy_discarded": self.occupancy_discarded,
        }


@dataclass(frozen=True, slots=True)
class VehicleSnapshot:
    """Posiciones leídas en un instante, con o sin ocupación."""

    vehicles: tuple[Vehicle, ...]
    fetched_at: datetime
    occupancy_available: bool


# Destinos habituales de cada sentido. En las terminales la fuente a veces no cuadra.
HABITUAL_DESTINATIONS: dict[tuple[int, int], tuple[str, str]] = {
    (1, 1): ("TRI", "La Trinidad"),
    (1, 2): ("INT", "Intercambiador"),
    (2, 1): ("CUE", "La Cuesta"),
    (2, 2): ("TIN", "Tíncer"),
}


def direction_label(line: int, direction: int) -> str:
    """Etiqueta corta del sentido, por ejemplo «Hacia La Trinidad»."""
    destination = HABITUAL_DESTINATIONS.get((line, direction))
    if destination is None:
        return f"Sentido {direction}"
    return f"Hacia {destination[1]}"
