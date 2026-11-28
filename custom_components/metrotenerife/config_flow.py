"""Configuración por la interfaz: una entrada y una subentrada por parada."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .vendor_bootstrap import bootstrap

bootstrap()

from metrotenerife import Catalog, load_catalog  # noqa: E402
from metrotenerife.models import Stop, direction_label  # noqa: E402
from metrotenerife.text import fold  # noqa: E402

from .const import (  # noqa: E402
    CONF_DIRECTION,
    CONF_LINES,
    CONF_NAME,
    CONF_QUERY,
    CONF_SCAN_INTERVAL,
    CONF_SEARCH_AGAIN,
    CONF_STOP_CODE,
    CONF_STOP_NAME,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    INTEGRATION_NAME,
    MAX_SCAN_INTERVAL_SECONDS,
    MIN_SCAN_INTERVAL_SECONDS,
    SUBENTRY_TYPE_STOP,
)


def _matches(catalog: Catalog, query: str) -> list[Stop]:
    """Código exacto, id GTFS o búsqueda por nombre."""
    text = query.strip()
    direct = catalog.get(text)
    if direct is not None and (
        fold(text) == fold(direct.code) or fold(text) == fold(direct.gtfs_id or "")
    ):
        return [direct]
    return catalog.search(text, limit=25)


def _interval_schema(default: int) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_SCAN_INTERVAL, default=default): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL_SECONDS,
                    max=MAX_SCAN_INTERVAL_SECONDS,
                    step=10,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="s",
                )
            )
        }
    )


def _clamp_interval(value: object) -> int:
    try:
        seconds = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_SCAN_INTERVAL_SECONDS
    return max(MIN_SCAN_INTERVAL_SECONDS, min(seconds, MAX_SCAN_INTERVAL_SECONDS))


def _entry_title(stop: Stop, lines: list[int], direction: int | None, custom: str) -> str:
    base = custom.strip() or f"{stop.name} ({stop.code})"
    extras: list[str] = []
    if len(lines) == 1:
        extras.append(f"L{lines[0]}")
    if direction is not None:
        line_for_label = (
            lines[0] if len(lines) == 1 else (stop.lines[0] if len(stop.lines) == 1 else None)
        )
        extras.append(
            direction_label(line_for_label, direction) if line_for_label else f"sentido {direction}"
        )
    if not extras:
        return base
    return f"{base} · {' '.join(extras)}"


def _unique_id(code: str, lines: list[int], direction: int | None) -> str:
    line_part = ",".join(str(line) for line in lines) or "*"
    direction_part = str(direction) if direction else "*"
    return f"{code}|{line_part}|{direction_part}"


class MetrotenerifeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Entrada única. Las paradas se añaden después, una a una."""

    VERSION = 1
    MINOR_VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> MetrotenerifeOptionsFlow:
        return MetrotenerifeOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: Any
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_TYPE_STOP: StopSubentryFlow}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        errors: dict[str, str] = {}
        if user_input is not None:
            seconds = _clamp_interval(user_input.get(CONF_SCAN_INTERVAL))
            if seconds < MIN_SCAN_INTERVAL_SECONDS:
                errors[CONF_SCAN_INTERVAL] = "interval_too_short"
            else:
                return self.async_create_entry(
                    title=INTEGRATION_NAME,
                    data={CONF_SCAN_INTERVAL: seconds},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=_interval_schema(DEFAULT_SCAN_INTERVAL_SECONDS),
            errors=errors,
        )


class MetrotenerifeOptionsFlow(OptionsFlow):
    """Cambia el intervalo de sondeo sin tocar las paradas."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = _clamp_interval(
            self.config_entry.options.get(
                CONF_SCAN_INTERVAL,
                self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS),
            )
        )
        if user_input is not None:
            seconds = _clamp_interval(user_input.get(CONF_SCAN_INTERVAL))
            if seconds < MIN_SCAN_INTERVAL_SECONDS:
                errors[CONF_SCAN_INTERVAL] = "interval_too_short"
            else:
                return self.async_create_entry(data={CONF_SCAN_INTERVAL: seconds})
        return self.async_show_form(
            step_id="init",
            data_schema=_interval_schema(current),
            errors=errors,
        )


class StopSubentryFlow(ConfigSubentryFlow):
    """Elige una parada y, si quieres, una línea y un sentido."""

    def __init__(self) -> None:
        super().__init__()
        self._matches: list[Stop] = []
        self._stop: Stop | None = None

    async def _catalog(self) -> Catalog:
        """El catálogo se lee del disco la primera vez; se hace fuera del event loop."""
        return await self.hass.async_add_executor_job(load_catalog)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            query = str(user_input.get(CONF_QUERY) or "").strip()
            matches = _matches(await self._catalog(), query) if query else []
            if not matches:
                errors[CONF_QUERY] = "stop_not_found"
            elif len(matches) == 1:
                self._stop = matches[0]
                return await self.async_step_configure()
            else:
                self._matches = matches
                return await self.async_step_select_stop()
        schema = vol.Schema(
            {vol.Required(CONF_QUERY): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))}
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors, last_step=False
        )

    async def async_step_select_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        valid = {stop.code: stop for stop in self._matches}
        if user_input is not None:
            if user_input.get(CONF_SEARCH_AGAIN):
                self._matches = []
                return await self.async_step_user()
            selected = str(user_input.get(CONF_STOP_CODE) or "")
            if selected not in valid:
                errors[CONF_STOP_CODE] = "stop_not_found"
            else:
                self._stop = valid[selected]
                return await self.async_step_configure()
        options = [
            SelectOptionDict(
                value=stop.code,
                label=f"{stop.code} — {stop.name} ({', '.join(f'L{line}' for line in stop.lines)})",
            )
            for stop in self._matches
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_STOP_CODE): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
                ),
                vol.Optional(CONF_SEARCH_AGAIN, default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="select_stop", data_schema=schema, errors=errors, last_step=False
        )

    async def async_step_configure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        reconfigure = (
            self._get_reconfigure_subentry() if self.source == SOURCE_RECONFIGURE else None
        )
        if self._stop is None and reconfigure is not None:
            catalog = await self._catalog()
            code = str(reconfigure.data[CONF_STOP_CODE])
            self._stop = catalog.get(code)
        if self._stop is None:
            return self.async_abort(reason="stop_not_found")
        stop = self._stop
        errors: dict[str, str] = {}
        if user_input is not None:
            if reconfigure is None and user_input.get(CONF_SEARCH_AGAIN):
                self._stop = None
                return await self.async_step_user()
            raw_lines = user_input.get(CONF_LINES) or []
            if isinstance(raw_lines, str):
                raw_lines = [raw_lines]
            try:
                lines = sorted({int(line) for line in raw_lines})
            except (TypeError, ValueError):
                lines = []
                errors[CONF_LINES] = "invalid_line"
            if any(line not in stop.lines for line in lines):
                errors[CONF_LINES] = "invalid_line"
            raw_direction = str(user_input.get(CONF_DIRECTION) or "")
            direction = int(raw_direction) if raw_direction in {"1", "2"} else None
            if not errors:
                data: dict[str, Any] = {
                    CONF_STOP_CODE: stop.code,
                    CONF_STOP_NAME: stop.name,
                    CONF_LINES: lines,
                }
                if direction is not None:
                    data[CONF_DIRECTION] = direction
                title = _entry_title(stop, lines, direction, str(user_input.get(CONF_NAME) or ""))
                unique_id = _unique_id(stop.code, lines, direction)
                if self._already_configured(
                    unique_id, exclude=reconfigure.subentry_id if reconfigure else None
                ):
                    return self.async_abort(reason="already_configured")
                if reconfigure is not None:
                    return self.async_update_and_abort(
                        self._get_entry(),
                        reconfigure,
                        title=title,
                        unique_id=unique_id,
                        data=data,
                    )
                return self.async_create_entry(title=title, unique_id=unique_id, data=data)

        return self.async_show_form(
            step_id="configure",
            data_schema=self.add_suggested_values_to_schema(
                self._configure_schema(stop, reconfigure is None),
                self._suggested(stop, reconfigure, user_input),
            ),
            errors=errors,
            description_placeholders={"stop_code": stop.code, "stop_name": stop.name},
            last_step=True,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        return await self.async_step_configure(user_input)

    def _already_configured(self, unique_id: str, *, exclude: str | None) -> bool:
        for subentry in self._get_entry().subentries.values():
            if subentry.subentry_type != SUBENTRY_TYPE_STOP:
                continue
            if exclude and subentry.subentry_id == exclude:
                continue
            if subentry.unique_id == unique_id:
                return True
        return False

    def _configure_schema(self, stop: Stop, include_search_again: bool) -> vol.Schema:
        line_options = [
            SelectOptionDict(value=str(line), label=f"L{line} — {direction_summary(stop, line)}")
            for line in stop.lines
        ]
        direction_options = [SelectOptionDict(value="", label="Cualquiera")]
        direction_options.extend(_direction_options(stop))
        fields: dict[Any, Any] = {
            vol.Optional(CONF_LINES): SelectSelector(
                SelectSelectorConfig(
                    options=line_options,
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(CONF_DIRECTION, default=""): SelectSelector(
                SelectSelectorConfig(options=direction_options, mode=SelectSelectorMode.DROPDOWN)
            ),
            vol.Optional(CONF_NAME): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
        }
        if include_search_again:
            fields[vol.Optional(CONF_SEARCH_AGAIN, default=False)] = BooleanSelector()
        return vol.Schema(fields)

    def _suggested(
        self, stop: Stop, reconfigure: Any, user_input: dict[str, Any] | None
    ) -> dict[str, Any]:
        suggested: dict[str, Any] = {
            CONF_NAME: f"{stop.name} ({stop.code})",
            CONF_LINES: [],
            CONF_DIRECTION: "",
        }
        if reconfigure is not None:
            suggested[CONF_NAME] = reconfigure.title
            suggested[CONF_LINES] = [str(line) for line in reconfigure.data.get(CONF_LINES) or []]
            direction = reconfigure.data.get(CONF_DIRECTION)
            suggested[CONF_DIRECTION] = str(direction) if direction else ""
        if user_input:
            suggested.update(user_input)
        return suggested


def direction_summary(stop: Stop, line: int) -> str:
    """Texto corto de los dos sentidos de una línea."""
    labels = [direction_label(line, direction) for direction in (1, 2)]
    if len(stop.lines) == 1:
        return " / ".join(label.removeprefix("Hacia ") for label in labels)
    return " / ".join(labels)


def _direction_options(stop: Stop) -> list[SelectOptionDict]:
    if stop.lines == (1,):
        return [
            SelectOptionDict(value="1", label="1 — Hacia La Trinidad"),
            SelectOptionDict(value="2", label="2 — Hacia Intercambiador"),
        ]
    if stop.lines == (2,):
        return [
            SelectOptionDict(value="1", label="1 — Hacia La Cuesta"),
            SelectOptionDict(value="2", label="2 — Hacia Tíncer"),
        ]
    return [
        SelectOptionDict(value="1", label="1 — L1 hacia La Trinidad, L2 hacia La Cuesta"),
        SelectOptionDict(value="2", label="2 — L1 hacia Intercambiador, L2 hacia Tíncer"),
    ]
