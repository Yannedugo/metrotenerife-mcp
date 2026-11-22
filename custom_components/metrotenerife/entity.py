"""Dispositivo por parada."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NetworkSnapshot, TranviaCoordinator


class MetrotenerifeStopEntity(CoordinatorEntity[TranviaCoordinator]):
    """Entidad ligada a una subentrada de parada."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: TranviaCoordinator, subentry_id: str, title: str, stop_code: str
    ) -> None:
        super().__init__(coordinator)
        self._subentry_id = subentry_id
        self._stop_code = stop_code
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry_id)},
            name=title,
            manufacturer="Metropolitano de Tenerife",
            model="Tranvía de Tenerife",
            configuration_url=f"https://tranviaonline.metrotenerife.com/#paneles/{stop_code}",
        )

    @property
    def snapshot(self) -> NetworkSnapshot | None:
        return self.coordinator.data
