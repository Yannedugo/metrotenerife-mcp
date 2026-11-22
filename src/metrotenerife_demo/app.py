"""Servidor de la demo. Solo habla con la librería `metrotenerife`."""

from __future__ import annotations

from pathlib import Path

from aiohttp import web

from metrotenerife.catalog import load_catalog
from metrotenerife.client import TranviaOnlineClient
from metrotenerife.errors import AmbiguousStopError, MetrotenerifeError, StopNotFoundError
from metrotenerife.models import Stop
from metrotenerife.operators import TranviaOperator
from metrotenerife.present import ambiguous_payload, proximos_payload, stop_payload

_INDEX = Path(__file__).resolve().parent / "index.html"
_CLIENT_KW: web.AppKey[dict[str, object]] = web.AppKey("client_kwargs", dict)
_CLIENT: web.AppKey[TranviaOnlineClient] = web.AppKey("client", TranviaOnlineClient)
_OPERATOR: web.AppKey[TranviaOperator] = web.AppKey("operator", TranviaOperator)


def create_app(**client_kwargs: object) -> web.Application:
    """Aplicación aiohttp. `client_kwargs` llega al cliente (en los tests, la URL falsa)."""
    app = web.Application()
    app[_CLIENT_KW] = dict(client_kwargs)
    app.on_startup.append(_start)
    app.on_cleanup.append(_close)
    app.router.add_get("/", _index)
    app.router.add_get("/api/paradas", _stops)
    app.router.add_get("/api/llegadas", _arrivals)
    return app


async def _start(app: web.Application) -> None:
    client = TranviaOnlineClient(**app[_CLIENT_KW])
    await client.__aenter__()
    app[_CLIENT] = client
    app[_OPERATOR] = TranviaOperator(client, load_catalog())


async def _close(app: web.Application) -> None:
    await app[_CLIENT].aclose()


async def _index(_request: web.Request) -> web.Response:
    return web.Response(text=_INDEX.read_text(encoding="utf-8"), content_type="text/html")


async def _stops(request: web.Request) -> web.Response:
    operator = request.app[_OPERATOR]
    query = request.query.get("q", "").strip()
    if query:
        stops = operator.search_stops(query, limit=25)
    else:
        stops = list(operator.catalog.stops)
    return web.json_response({"paradas": [stop_payload(stop) for stop in stops]})


async def _arrivals(request: web.Request) -> web.Response:
    operator = request.app[_OPERATOR]
    stop_query = request.query.get("parada", "").strip()
    if not stop_query:
        return _error("Indica una parada.", 400)
    try:
        line = _optional_choice(request.query.get("linea"), (1, 2), "La línea tiene que ser 1 o 2.")
    except ValueError as err:
        return _error(str(err), 400)
    try:
        stop, arrivals, fetched_at, notes = await operator.arrivals(
            stop_query, line=line, per_direction=3
        )
    except AmbiguousStopError as err:
        matches = [match for match in err.matches if isinstance(match, Stop)]
        return web.json_response(ambiguous_payload(operator.id, stop_query, matches, str(err)))
    except StopNotFoundError as err:
        return _error(str(err), 404)
    except MetrotenerifeError as err:
        return _error(str(err), 502)
    return web.json_response(
        proximos_payload(
            operator_id=operator.id,
            stop=stop,
            arrivals=arrivals,
            fetched_at=fetched_at,
            line=line,
            direction=None,
            destination=None,
            per_direction=3,
            notes=notes,
        )
    )


def _optional_choice(raw: str | None, allowed: tuple[int, ...], message: str) -> int | None:
    if raw is None or not raw.strip():
        return None
    try:
        value = int(raw)
    except ValueError as err:
        raise ValueError(message) from err
    if value not in allowed:
        raise ValueError(message)
    return value


def _error(message: str, status: int) -> web.Response:
    return web.json_response({"error": message}, status=status)
