"""Constantes de la integración del Tranvía de Tenerife."""

from __future__ import annotations

DOMAIN = "metrotenerife"
INTEGRATION_NAME = "Tranvía de Tenerife"
VERSION = "0.1.0"

SUBENTRY_TYPE_STOP = "stop"

CONF_STOP_CODE = "stop_code"
CONF_STOP_NAME = "stop_name"
CONF_LINES = "lines"
CONF_DIRECTION = "direction"
CONF_QUERY = "query"
CONF_SEARCH_AGAIN = "search_again"
CONF_NAME = "name"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL_SECONDS = 90
MIN_SCAN_INTERVAL_SECONDS = 60
MAX_SCAN_INTERVAL_SECONDS = 600
POLL_JITTER_SECONDS = 15
MANUAL_REFRESH_COOLDOWN_SECONDS = 60.0

HTTP_TIMEOUT_SECONDS = 12.0
CACHE_TTL_SECONDS = 20.0
MIN_REQUEST_INTERVAL_SECONDS = 1.0
MAX_ARRIVALS_ATTRIBUTE = 8

USER_AGENT = (
    f"HomeAssistant-Metrotenerife/{VERSION} (+https://github.com/Yannedugo/metrotenerife-mcp)"
)
