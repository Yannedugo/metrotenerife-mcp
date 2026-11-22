"""Un solo sondeo para todas las paradas configuradas."""

from __future__ import annotations

import logging
import math
import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from metrotenerife import Arrival, TranviaOnlineClient, filter_arrivals, load_catalog
from metrotenerife.errors import MetrotenerifeError
from metrotenerife.operators import compose_board, label_arrival

from .const import (
    CONF_DIRECTION,
    CONF_LINES,
    CONF_SCAN_INTERVAL,
    CONF_STOP_CODE,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    MANUAL_REFRESH_COOLDOWN_SECONDS,
    MAX_SCAN_INTERVAL_SECONDS,
    MIN_SCAN_INTERVAL_SECONDS,
    POLL_JITTER_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NetworkSnapshot:
    """Paneles leídos en una sola petición."""

    fetched_at: datetime
    by_stop: dict[str, tuple[Arrival, ...]]


def scan_interval_seconds(entry: ConfigEntry) -> int:
    """Intervalo efectivo, nunca por debajo del mínimo prudente."""
    raw = entry.options.get(
        CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS)
    )
    try:
        seconds = int(raw)
    except (TypeError, ValueError):
        seconds = DEFAULT_SCAN_INTERVAL_SECONDS
    return max(MIN_SCAN_INTERVAL_SECONDS, min(seconds, MAX_SCAN_INTERVAL_SECONDS))


class TranviaCoordinator(DataUpdateCoordinator[NetworkSnapshot]):
    """Lee `/api/infoStops/infoPanel` una vez por ciclo, para todas las paradas."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: TranviaOnlineClient
    ) -> None:
        self.client = client
        self._catalog = load_catalog()
        self._last_manual_refresh = None
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=self._next_interval(),
            always_update=False,
        )

    def _next_interval(self) -> timedelta:
        base = scan_interval_seconds(self.config_entry)
        return timedelta(seconds=base + random.uniform(0, POLL_JITTER_SECONDS))

    def arrivals_for(self, subentry: ConfigSubentry) -> list[Arrival]:
        """Llegadas de una parada, ya filtradas por línea y sentido."""
        if self.data is None:
            return []
        code = str(subentry.data[CONF_STOP_CODE])
        raw = self.data.by_stop.get(code, ())
        lines = tuple(int(line) for line in subentry.data.get(CONF_LINES) or [])
        direction = subentry.data.get(CONF_DIRECTION)
        return filter_arrivals(
            raw,
            lines=lines,
            direction=int(direction) if direction else None,
        )

    async def _async_update_data(self) -> NetworkSnapshot:
        self.update_interval = self._next_interval()
        try:
            grouped = await self.client.panels()
        except MetrotenerifeError as err:
            raise UpdateFailed(str(err)) from err
        fetched_at = datetime.now(UTC)
        try:
            snapshot = await self.client.vehicles()
            vehicles = list(snapshot.vehicles)
        except MetrotenerifeError:
            _LOGGER.warning("No se pudo leer la posición de los tranvías")
            vehicles = []
        labeled: dict[str, tuple[Arrival, ...]] = {}
        for code, arrivals in grouped.items():
            named = [label_arrival(arrival, self._catalog) for arrival in arrivals]
            board, _notes = compose_board(
                named,
                vehicles,
                self._catalog,
                per_direction=3,
                now=fetched_at,
            )
            labeled[code] = tuple(board)
        return NetworkSnapshot(fetched_at=fetched_at, by_stop=labeled)

    async def async_manual_refresh(self) -> None:
        """Refresco manual con una espera mínima para no insistir."""
        now = time.monotonic()
        if self._last_manual_refresh is not None:
            elapsed = now - self._last_manual_refresh
            if elapsed < MANUAL_REFRESH_COOLDOWN_SECONDS:
                remaining = math.ceil(MANUAL_REFRESH_COOLDOWN_SECONDS - elapsed)
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="refresh_cooldown",
                    translation_placeholders={"seconds": str(remaining)},
                )
        self._last_manual_refresh = now
        await self.async_request_refresh()
