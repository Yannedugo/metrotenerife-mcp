"""Endpoints de la página local, contra las fixtures y sin TranvíaOnline."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from aiohttp.test_utils import TestClient, TestServer

from metrotenerife_demo.__main__ import configure_logging
from metrotenerife_demo.app import create_app

FROZEN = datetime(2026, 11, 22, 14, 7, tzinfo=UTC)


def _app(api: dict):
    return create_app(base_url=api["base_url"], min_interval=0, cache_ttl=30, max_retries=0)


async def test_index_is_a_local_spanish_page(api) -> None:
    async with TestClient(TestServer(_app(api))) as http:
        response = await http.get("/")
        html = await response.text()
    assert response.status == 200
    assert "Tranvía de Tenerife" in html
    assert "Actualizar ahora" in html
    assert "60000" in html
    assert "tranviaonline.metrotenerife.com/#paneles/" in html
    assert "cdn" not in html.lower()
    assert "unpkg" not in html.lower()


async def test_stop_search_uses_the_catalog(api) -> None:
    async with TestClient(TestServer(_app(api))) as http:
        all_stops = await (await http.get("/api/paradas")).json()
        found = await (await http.get("/api/paradas", params={"q": "guimera"})).json()
    assert len(all_stops["paradas"]) == 25
    assert found["paradas"][0]["codigo"] == "GUI"


async def test_arrivals_match_the_agent_payload_and_use_the_cache(api) -> None:
    app = create_app(
        base_url=api["base_url"],
        min_interval=0,
        cache_ttl=30,
        max_retries=0,
        clock=lambda: FROZEN,
    )
    async with TestClient(TestServer(app)) as http:
        first = await http.get("/api/llegadas", params={"parada": "INT"})
        body = await first.json()
        second = await http.get("/api/llegadas", params={"parada": "Intercambiador", "linea": "1"})
        filtered = await second.json()
    assert first.status == 200
    assert body["aviso"].startswith("Datos en vivo")
    assert body["actualizacion_fuente"] == "2026-11-22T14:06:54+00:00"
    assert body["parada"]["codigo"] == "INT"
    assert [item["minutos"] for item in body["llegadas"]] == [11, 16]
    assert body["llegadas"][0]["destino"] == "La Trinidad"
    assert body["llegadas"][0]["ocupacion_porcentaje"] == 28
    assert body["llegadas"][0]["ocupacion_fresca"] is True
    assert body["llegadas"][1]["ocupacion_porcentaje"] is None
    assert body["llegadas"][1]["ocupacion_fresca"] is False
    assert "porcentaje" in body["llegadas"][0]["ocupacion_significado"].lower()
    assert body["llegadas"][0]["sentido_etiqueta"] == "Hacia La Trinidad"
    assert filtered["filtros"]["linea"] == 1
    assert api["hits"].count("INT") == 1


async def test_arrivals_reject_a_missing_or_unknown_stop(api) -> None:
    async with TestClient(TestServer(_app(api))) as http:
        empty = await http.get("/api/llegadas")
        missing = await http.get("/api/llegadas", params={"parada": "no-existe"})
        bad_line = await http.get("/api/llegadas", params={"parada": "INT", "linea": "9"})
        ambiguous = await http.get("/api/llegadas", params={"parada": "hospital"})
        ambiguous_body = await ambiguous.json()
    assert empty.status == 400
    assert missing.status == 404
    assert bad_line.status == 400
    assert ambiguous.status == 200
    assert ambiguous_body["ambiguo"] is True
    assert {stop["codigo"] for stop in ambiguous_body["paradas"]} == {"CAN", "HOS"}


def test_debug_flag_enables_library_logs() -> None:
    configure_logging(True)
    assert logging.getLogger("metrotenerife").level == logging.DEBUG
    configure_logging(False)
    assert logging.getLogger("metrotenerife").level == logging.INFO
