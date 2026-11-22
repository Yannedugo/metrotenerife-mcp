"""Botón para consultar el panel sin esperar al siguiente ciclo."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MetrotenerifeConfigEntry
from .const import CONF_STOP_CODE, SUBENTRY_TYPE_STOP
from .coordinator import TranviaCoordinator
from .entity import MetrotenerifeStopEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MetrotenerifeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Un botón de actualización por parada. Todos comparten el mismo sondeo."""
    coordinator = entry.runtime_data.coordinator
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_STOP:
            continue
        async_add_entities(
            [
                RefreshButton(
                    coordinator,
                    subentry.subentry_id,
                    subentry.title,
                    str(subentry.data[CONF_STOP_CODE]),
                )
            ],
            config_subentry_id=subentry.subentry_id,
        )


class RefreshButton(MetrotenerifeStopEntity, ButtonEntity):
    """Pide una lectura nueva, con una espera mínima de un minuto."""

    _attr_icon = "mdi:refresh"
    _attr_translation_key = "refresh"

    def __init__(
        self, coordinator: TranviaCoordinator, subentry_id: str, title: str, stop_code: str
    ) -> None:
        super().__init__(coordinator, subentry_id, title, stop_code)
        self._attr_unique_id = f"{subentry_id}_refresh"

    async def async_press(self) -> None:
        await self.coordinator.async_manual_refresh()
