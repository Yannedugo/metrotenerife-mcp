"""Herramientas MCP sobre la librería común.

El SDK oficial 2.x llama `MCPServer` a lo que antes era FastMCP. El transporte
por defecto es stdio; `streamable-http` sirve para alojarlo más adelante.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse

from metrotenerife import __version__
from metrotenerife.client import TranviaOnlineClient
from metrotenerife.errors import (
    AmbiguousStopError,
    MetrotenerifeError,
    OperatorNotFoundError,
    StopNotFoundError,
)
from metrotenerife.models import Stop, direction_label
from metrotenerife.operators import (
    AVISO_CATALOGO,
    AVISO_EN_VIVO,
    OperatorRegistry,
    TransitOperator,
    TranviaOperator,
)
from metrotenerife.present import (
    ambiguous_payload,
    forecast_payload,
    proximos_payload,
    stop_payload,
    vehicle_query_payload,
    vehicle_state_payload,
)

INSTRUCTIONS = (
    "Servidor no oficial de tiempos en vivo del Tranvía de Tenerife (Metrotenerife). "
    "Usa buscar_parada si la persona dice un nombre y no un código de tres letras. "
    "proximos_tranvias, estado_tranvias e info_vehiculo son datos en vivo: di la hora de "
    "actualización y que la fuente no es una API oficial. El número de vehículo es el que va "
    "pintado en el tranvía; si falta o la fila es vieja, di que es desconocido. "
    "prevision_tranvias es una previsión teórica: di que no es el horario oficial y distingue "
    "en_vivo, estimado y previsto. Para una hora futura pasa desde en ISO, hora canaria. "
    "info_lineas es un catálogo estático, no un horario. "
    "De momento el único operador es 'tranvia'; el parámetro operador existe para añadir otros."
)


def build_server(**client_kwargs: Any) -> MCPServer:
    """Construye el servidor. `client_kwargs` llega al cliente HTTP (tests y base_url)."""

    @asynccontextmanager
    async def lifespan(_server: MCPServer) -> AsyncIterator[dict[str, Any]]:
        async with TranviaOnlineClient(**client_kwargs) as client:
            registry = OperatorRegistry()
            registry.register(TranviaOperator(client))
            yield {"registry": registry}

    server = MCPServer(
        "metrotenerife",
        title="Tranvía de Tenerife",
        instructions=INSTRUCTIONS,
        version=__version__,
        website_url="https://github.com/Yannedugo/metrotenerife-mcp",
        lifespan=lifespan,
    )

    @server.tool(
        description=(
            "Busca una parada del tranvía por nombre o código, sin distinguir tildes ni mayúsculas."
        )
    )
    async def buscar_parada(
        consulta: str, limite: int = 8, operador: str = "tranvia", *, ctx: Context
    ) -> str:
        """Busca paradas en el catálogo estático."""
        registry = _registry(ctx)
        operator = _operator(registry, operador)
        bounded = max(1, min(limite, 25))
        stops = operator.search_stops(consulta, limit=bounded)
        return _dump(
            {
                "aviso": AVISO_CATALOGO,
                "operador": operator.id,
                "consulta": consulta,
                "paradas": [stop_payload(stop) for stop in stops],
            }
        )

    @server.tool(
        description=(
            "Próximos tranvías en una parada. Acepta código (INT) o nombre. "
            "linea (1 o 2), sentido (1 o 2) y destino son opcionales."
        )
    )
    async def proximos_tranvias(
        parada: str,
        linea: int | None = None,
        sentido: int | None = None,
        destino: str | None = None,
        por_sentido: int = 3,
        operador: str = "tranvia",
        *,
        ctx: Context,
    ) -> str:
        """Llegadas en vivo. Lo que pase de las anunciadas por sentido va marcado como estimado."""
        _validate_filters(linea, sentido)
        if por_sentido < 1 or por_sentido > 6:
            raise ToolError("por_sentido tiene que estar entre 1 y 6.")
        registry = _registry(ctx)
        operator = _operator(registry, operador)
        try:
            stop, arrivals, fetched_at, notes = await operator.arrivals(
                parada,
                line=linea,
                direction=sentido,
                destination=destino,
                per_direction=por_sentido,
            )
        except AmbiguousStopError as err:
            matches = [match for match in err.matches if isinstance(match, Stop)]
            return _dump(ambiguous_payload(operator.id, parada, matches, str(err)))
        except StopNotFoundError as err:
            raise ToolError(str(err)) from err
        except MetrotenerifeError as err:
            raise ToolError(str(err)) from err
        return _dump(
            proximos_payload(
                operator_id=operator.id,
                stop=stop,
                arrivals=arrivals,
                fetched_at=fetched_at,
                line=linea,
                direction=sentido,
                destination=destino,
                per_direction=por_sentido,
                notes=notes,
            )
        )

    @server.tool(
        description=(
            "Previsión teórica de pasos por una parada. No es el horario oficial. "
            "parada: código (GRA) o nombre (Gracia). sentido: 1 o 2, opcional. "
            "En la línea 1, 1 va a La Trinidad y 2 a Intercambiador. "
            "En la línea 2, 1 va a La Cuesta y 2 a Tíncer. "
            "desde: ISO, sin zona se lee en Canarias; por defecto ahora. hasta (fin exclusive) "
            "o minutos (duración, por defecto 90, máximo 1440). Cada paso trae hora, linea, "
            "destino y tipo: en_vivo si lo anuncia el panel, estimado si sale de la posición, "
            "previsto si solo es el intervalo publicado. Si desde cae en la próxima media hora, "
            "mezcla esos datos reales. Ejemplo: parada Gracia, sentido 1, "
            "desde 2026-11-23T07:50:00, minutos 30, para mañana a las 7:50 hacia La Trinidad."
        )
    )
    async def prevision_tranvias(
        parada: str,
        sentido: int | None = None,
        desde: str | None = None,
        hasta: str | None = None,
        minutos: int | None = None,
        linea: int | None = None,
        operador: str = "tranvia",
        *,
        ctx: Context,
    ) -> str:
        """Pasos previstos. Los tipos en_vivo y estimado solo aparecen cerca de ahora."""
        _validate_filters(linea, sentido)
        registry = _registry(ctx)
        operator = _operator(registry, operador)
        try:
            stop, passages, start, end, mixed, note = await operator.forecast(
                parada,
                desde=desde,
                hasta=hasta,
                minutos=minutos,
                line=linea,
                direction=sentido,
            )
        except AmbiguousStopError as err:
            matches = [match for match in err.matches if isinstance(match, Stop)]
            return _dump(ambiguous_payload(operator.id, parada, matches, str(err)))
        except StopNotFoundError as err:
            raise ToolError(str(err)) from err
        except ValueError as err:
            raise ToolError(str(err)) from err
        except MetrotenerifeError as err:
            raise ToolError(str(err)) from err
        return _dump(
            forecast_payload(
                operator_id=operator.id,
                stop=stop,
                passages=passages,
                start=start,
                end=end,
                mixed=mixed,
                note=note,
            )
        )

    @server.tool(
        description="Posición de los tranvías y ocupación, si el dato de ocupación es reciente."
    )
    async def estado_tranvias(
        linea: int | None = None,
        operador: str = "tranvia",
        *,
        ctx: Context,
    ) -> str:
        """Posiciones en vivo."""
        _validate_filters(linea, None)
        registry = _registry(ctx)
        operator = _operator(registry, operador)
        try:
            snapshot = await operator.vehicles(line=linea)
        except MetrotenerifeError as err:
            raise ToolError(str(err)) from err
        return _dump(
            {
                "aviso": AVISO_EN_VIVO,
                "operador": operator.id,
                "obtenido_a": snapshot.fetched_at.isoformat(),
                "actualizacion_fuente": None,
                "nota_posicion": (
                    "Las posiciones no traen marca de tiempo propia: "
                    "«obtenido_a» es el momento de la consulta. "
                    "La ocupación antigua se descarta."
                ),
                "ocupacion_disponible": snapshot.occupancy_available,
                "tranvias": [vehicle_state_payload(vehicle) for vehicle in snapshot.vehicles],
            }
        )

    @server.tool(
        description=(
            "Consulta un tranvía por el número pintado en la unidad. "
            "Devuelve servicio, línea, destino, posición, próxima parada y ocupación "
            "solo si el dato es reciente. Si no circula o la fila es vieja, lo dice."
        )
    )
    async def info_vehiculo(
        numero: int,
        operador: str = "tranvia",
        *,
        ctx: Context,
    ) -> str:
        """Estado de una unidad por su número, no por el servicio."""
        if numero < 1:
            raise ToolError("El número de vehículo tiene que ser un entero positivo.")
        registry = _registry(ctx)
        operator = _operator(registry, operador)
        try:
            report = await operator.describe_vehicle(numero)
        except ValueError as err:
            raise ToolError(str(err)) from err
        except MetrotenerifeError as err:
            raise ToolError(str(err)) from err
        return _dump(vehicle_query_payload(report))

    @server.tool(description="Líneas, sentidos y paradas en orden. Es catálogo, no un horario.")
    async def info_lineas(
        linea: int | None = None,
        operador: str = "tranvia",
        *,
        ctx: Context,
    ) -> str:
        """Información estática de las líneas."""
        _validate_filters(linea, None)
        registry = _registry(ctx)
        operator = _operator(registry, operador)
        lines = operator.lines()
        if linea is not None:
            lines = [item for item in lines if item.line == linea]
        stops = {stop.code: stop for stop in operator.catalog.stops}
        payload_lines = []
        for item in lines:
            directions = []
            for direction in item.directions:
                directions.append(
                    {
                        "sentido": direction.direction,
                        "etiqueta": direction_label(item.line, direction.direction),
                        "destino": direction.destination_name,
                        "destino_codigo": direction.destination_code,
                        "paradas": [
                            {
                                "codigo": code,
                                "nombre": stops[code].name if code in stops else code,
                            }
                            for code in direction.stop_codes
                        ],
                    }
                )
            payload_lines.append(
                {
                    "linea": item.line,
                    "codigo": item.code,
                    "nombre": item.name,
                    "descripcion": item.description,
                    "sentidos": directions,
                }
            )
        return _dump(
            {
                "aviso": AVISO_CATALOGO,
                "operador": operator.id,
                "atribucion": operator.catalog.attribution,
                "lineas": payload_lines,
            }
        )

    @server.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "operador": "tranvia"})

    return server


def _registry(ctx: Context) -> OperatorRegistry:
    registry = ctx.request_context.lifespan_context.get("registry")
    if not isinstance(registry, OperatorRegistry):
        raise ToolError("El servidor no tiene un registro de operadores.")
    return registry


def _operator(registry: OperatorRegistry, operator_id: str) -> TransitOperator:
    try:
        return registry.get(operator_id)
    except OperatorNotFoundError as err:
        raise ToolError(str(err)) from err


def _validate_filters(line: int | None, direction: int | None) -> None:
    if line is not None and line not in (1, 2):
        raise ToolError("La línea tiene que ser 1 o 2.")
    if direction is not None and direction not in (1, 2):
        raise ToolError("El sentido tiene que ser 1 o 2.")


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
