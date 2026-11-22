"""Sensores de próximo tranvía: hora estimada y minutos."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from metrotenerife import Arrival
from metrotenerife.models import OCCUPANCY_MEANING, direction_label

from . import MetrotenerifeConfigEntry
from .const import (
    CONF_DIRECTION,
    CONF_LINES,
    CONF_STOP_CODE,
    CONF_STOP_NAME,
    MAX_ARRIVALS_ATTRIBUTE,
    SUBENTRY_TYPE_STOP,
)
from .coordinator import TranviaCoordinator
from .entity import MetrotenerifeStopEntity

PARALLEL_UPDATES = 0


def _cleanup_orphaned_line_sensors(
    hass: HomeAssistant,
    entry: MetrotenerifeConfigEntry,
    subentry_id: str,
    active_unique_ids: set[str],
) -> None:
    """Quita sensores de línea que ya no están en el filtro."""
    registry = er.async_get(hass)
    prefix = f"{subentry_id}_line_"
    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            entity_entry.domain == Platform.SENSOR
            and entity_entry.unique_id.startswith(prefix)
            and entity_entry.unique_id not in active_unique_ids
            and entity_entry.config_subentry_id == subentry_id
        ):
            registry.async_remove(entity_entry.entity_id)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MetrotenerifeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crea los sensores de cada parada configurada."""
    coordinator = entry.runtime_data.coordinator
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_STOP:
            continue
        lines = tuple(int(line) for line in subentry.data.get(CONF_LINES) or [])
        entities: list[SensorEntity] = [
            NextTramSensor(
                coordinator,
                subentry.subentry_id,
                subentry.title,
                str(subentry.data[CONF_STOP_CODE]),
            ),
            MinutesSensor(
                coordinator,
                subentry.subentry_id,
                subentry.title,
                str(subentry.data[CONF_STOP_CODE]),
            ),
        ]
        active = {f"{subentry.subentry_id}_next_tram", f"{subentry.subentry_id}_minutes"}
        for line in lines:
            sensor = LineNextTramSensor(
                coordinator,
                subentry.subentry_id,
                subentry.title,
                str(subentry.data[CONF_STOP_CODE]),
                line,
            )
            entities.append(sensor)
            active.add(f"{subentry.subentry_id}_line_{line}")
        _cleanup_orphaned_line_sensors(hass, entry, subentry.subentry_id, active)
        async_add_entities(entities, config_subentry_id=subentry.subentry_id)


def _arrival_attribute(arrival: Arrival) -> dict[str, Any]:
    return {
        "line": arrival.line,
        "direction": arrival.direction,
        "direction_label": direction_label(arrival.line, arrival.direction),
        "destination": arrival.destination_name,
        "destination_code": arrival.destination_code,
        "minutes": arrival.minutes,
        "estimated_arrival": arrival.estimated_arrival.isoformat(),
        "service": arrival.service,
        "updated_at": arrival.updated_at.isoformat(),
        "occupancy_percent": arrival.occupancy_percent if arrival.occupancy_fresh else None,
        "occupancy_fresh": arrival.occupancy_fresh,
        "occupancy_updated_at": (
            arrival.occupancy_updated_at.isoformat() if arrival.occupancy_updated_at else None
        ),
        "occupancy_meaning": OCCUPANCY_MEANING,
    }


class _StopSensor(MetrotenerifeStopEntity, SensorEntity):
    def __init__(
        self, coordinator: TranviaCoordinator, subentry_id: str, title: str, stop_code: str
    ) -> None:
        super().__init__(coordinator, subentry_id, title, stop_code)
        self._subentry_id = subentry_id

    def _subentry(self) -> Any:
        return self.coordinator.config_entry.subentries[self._subentry_id]

    def _arrivals(self) -> list[Arrival]:
        return self.coordinator.arrivals_for(self._subentry())

    def _next(self) -> Arrival | None:
        arrivals = self._arrivals()
        return arrivals[0] if arrivals else None


class NextTramSensor(_StopSensor):
    """Hora estimada del próximo tranvía. Home Assistant muestra la cuenta atrás."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:tram"
    _attr_translation_key = "next_tram"
    _unrecorded_attributes = frozenset({"arrivals"})

    def __init__(
        self, coordinator: TranviaCoordinator, subentry_id: str, title: str, stop_code: str
    ) -> None:
        super().__init__(coordinator, subentry_id, title, stop_code)
        self._attr_unique_id = f"{subentry_id}_next_tram"

    @property
    def native_value(self) -> datetime | None:
        arrival = self._next()
        return arrival.estimated_arrival if arrival else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        subentry = self._subentry()
        arrival = self._next()
        arrivals = self._arrivals()
        data = self.coordinator.data
        return {
            "stop_code": subentry.data.get(CONF_STOP_CODE),
            "stop_name": subentry.data.get(CONF_STOP_NAME),
            "filtered_lines": list(subentry.data.get(CONF_LINES) or []),
            "filtered_direction": subentry.data.get(CONF_DIRECTION),
            "line": arrival.line if arrival else None,
            "direction": arrival.direction if arrival else None,
            "direction_label": direction_label(arrival.line, arrival.direction)
            if arrival
            else None,
            "destination": arrival.destination_name if arrival else None,
            "destination_code": arrival.destination_code if arrival else None,
            "minutes": arrival.minutes if arrival else None,
            "service": arrival.service if arrival else None,
            "occupancy_percent": (
                arrival.occupancy_percent if arrival and arrival.occupancy_fresh else None
            ),
            "occupancy_fresh": arrival.occupancy_fresh if arrival else False,
            "occupancy_meaning": OCCUPANCY_MEANING,
            "arrivals_count": len(arrivals),
            "arrivals": [_arrival_attribute(item) for item in arrivals[:MAX_ARRIVALS_ATTRIBUTE]],
            "source_updated_at": arrival.updated_at.isoformat() if arrival else None,
            "fetched_at": data.fetched_at.isoformat() if data else None,
        }


class MinutesSensor(_StopSensor):
    """Minutos que anuncia el panel. Útil en automatizaciones numéricas."""

    _attr_icon = "mdi:timer-outline"
    _attr_translation_key = "minutes"
    _attr_native_unit_of_measurement = "min"
    _attr_suggested_display_precision = 0

    def __init__(
        self, coordinator: TranviaCoordinator, subentry_id: str, title: str, stop_code: str
    ) -> None:
        super().__init__(coordinator, subentry_id, title, stop_code)
        self._attr_unique_id = f"{subentry_id}_minutes"

    @property
    def native_value(self) -> int | None:
        arrival = self._next()
        return arrival.minutes if arrival else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        arrival = self._next()
        if arrival is None:
            return {"line": None, "destination": None, "arriving": False}
        return {
            "line": arrival.line,
            "direction": arrival.direction,
            "destination": arrival.destination_name,
            "destination_code": arrival.destination_code,
            "service": arrival.service,
            "arriving": arrival.minutes == 0,
            "estimated_arrival": arrival.estimated_arrival.isoformat(),
            "occupancy_percent": arrival.occupancy_percent if arrival.occupancy_fresh else None,
            "occupancy_fresh": arrival.occupancy_fresh,
            "occupancy_meaning": OCCUPANCY_MEANING,
        }


class LineNextTramSensor(_StopSensor):
    """Próximo tranvía de una línea concreta, si el filtro de líneas no está vacío."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:tram"
    _attr_translation_key = "line_next_tram"

    def __init__(
        self,
        coordinator: TranviaCoordinator,
        subentry_id: str,
        title: str,
        stop_code: str,
        line: int,
    ) -> None:
        super().__init__(coordinator, subentry_id, title, stop_code)
        self._line = line
        self._attr_unique_id = f"{subentry_id}_line_{line}"
        self._attr_translation_placeholders = {"line": str(line)}

    def _line_arrivals(self) -> list[Arrival]:
        return [arrival for arrival in self._arrivals() if arrival.line == self._line]

    @property
    def native_value(self) -> datetime | None:
        arrivals = self._line_arrivals()
        return arrivals[0].estimated_arrival if arrivals else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        arrivals = self._line_arrivals()
        first = arrivals[0] if arrivals else None
        return {
            "line": self._line,
            "destination": first.destination_name if first else None,
            "destination_code": first.destination_code if first else None,
            "direction": first.direction if first else None,
            "minutes": first.minutes if first else None,
            "service": first.service if first else None,
            "occupancy_percent": (
                first.occupancy_percent if first and first.occupancy_fresh else None
            ),
            "occupancy_fresh": first.occupancy_fresh if first else False,
            "occupancy_meaning": OCCUPANCY_MEANING,
            "following_arrivals": [_arrival_attribute(item) for item in arrivals[1:4]],
        }
