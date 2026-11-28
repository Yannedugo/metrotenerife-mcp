"""Integración de Home Assistant para el Tranvía de Tenerife."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CACHE_TTL_SECONDS,
    HTTP_TIMEOUT_SECONDS,
    MIN_REQUEST_INTERVAL_SECONDS,
    SUBENTRY_TYPE_STOP,
    USER_AGENT,
)
from .coordinator import TranviaCoordinator
from .vendor.metrotenerife import TranviaOnlineClient, load_catalog
from .vendor.metrotenerife.forecast import load_schedule

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]


@dataclass(slots=True)
class MetrotenerifeRuntimeData:
    """Cliente compartido y coordinador de todos los paneles."""

    client: TranviaOnlineClient
    coordinator: TranviaCoordinator


MetrotenerifeConfigEntry = ConfigEntry[MetrotenerifeRuntimeData]


def _has_stops(entry: ConfigEntry) -> bool:
    return any(
        subentry.subentry_type == SUBENTRY_TYPE_STOP for subentry in entry.subentries.values()
    )


async def async_setup_entry(hass: HomeAssistant, entry: MetrotenerifeConfigEntry) -> bool:
    """Crea el cliente y, si hay paradas, hace la primera lectura."""
    # El catálogo y la tabla de frecuencias se leen del disco una vez, fuera
    # del event loop. Después quedan en memoria para sensores y previsión.
    catalog = await hass.async_add_executor_job(load_catalog)
    schedule = await hass.async_add_executor_job(load_schedule)
    session = async_get_clientsession(hass)
    client = TranviaOnlineClient(
        session,
        timeout=HTTP_TIMEOUT_SECONDS,
        cache_ttl=CACHE_TTL_SECONDS,
        min_interval=MIN_REQUEST_INTERVAL_SECONDS,
        user_agent=USER_AGENT,
    )
    coordinator = TranviaCoordinator(hass, entry, client, catalog=catalog, schedule=schedule)
    entry.runtime_data = MetrotenerifeRuntimeData(client=client, coordinator=coordinator)

    # Sin paradas no hace falta sondear. La primera parada recarga la entrada.
    if _has_stops(entry):
        await coordinator.async_config_entry_first_refresh()
    else:
        coordinator.update_interval = None

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MetrotenerifeConfigEntry) -> bool:
    """Descarga sensores y botones. La sesión HTTP es la de Home Assistant."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: MetrotenerifeConfigEntry) -> None:
    _LOGGER.debug("Recargando Tranvía de Tenerife tras un cambio de configuración")
    await hass.config_entries.async_reload(entry.entry_id)
