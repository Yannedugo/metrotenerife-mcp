"""Fixtures grabadas. No se llama a TranvíaOnline."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from aiohttp import web

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def fixture():
    return load_fixture


@pytest.fixture
async def api(fixture):
    """Servidor local con las respuestas grabadas."""
    hits: list[str] = []
    state = {"failures": 0}

    async def panel_int(_request: web.Request) -> web.Response:
        hits.append("INT")
        return web.json_response(fixture("info_panel_int.json"))

    async def panel_missing(_request: web.Request) -> web.Response:
        hits.append("missing")
        return web.Response(status=404, text="no")

    async def panel_all(_request: web.Request) -> web.Response:
        hits.append("all")
        return web.json_response(fixture("info_panel_all.json"))

    async def panel_bad(_request: web.Request) -> web.Response:
        hits.append("bad")
        return web.Response(text="esto no es json", content_type="application/json")

    async def panel_slow(_request: web.Request) -> web.Response:
        hits.append("slow")
        await asyncio.sleep(1)
        return web.json_response(fixture("info_panel_int.json"))

    async def panel_flaky(_request: web.Request) -> web.Response:
        hits.append("flaky")
        state["failures"] += 1
        if state["failures"] < 3:
            return web.Response(status=500, text="no", headers={"Retry-After": "0"})
        return web.json_response(fixture("info_panel_int.json"))

    async def vehicles(_request: web.Request) -> web.Response:
        hits.append("vehicles")
        return web.json_response(fixture("vehicle_location.json"))

    async def occupancy(_request: web.Request) -> web.Response:
        hits.append("occupancy")
        return web.json_response(fixture("carga_vehiculo.json"))

    app = web.Application()
    app.router.add_get("/api/infoStops/infoPanel/INT", panel_int)
    app.router.add_get("/api/infoStops/infoPanel/ZZZ", panel_missing)
    app.router.add_get("/api/infoStops/infoPanel/BAD", panel_bad)
    app.router.add_get("/api/infoStops/infoPanel/SLOW", panel_slow)
    app.router.add_get("/api/infoStops/infoPanel/FLKY", panel_flaky)
    app.router.add_get("/api/infoStops/infoPanel", panel_all)
    app.router.add_get("/api/infoStops/vehicleLocation", vehicles)
    app.router.add_get("/api/cargaVehiculo", occupancy)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = site._server.sockets  # type: ignore[union-attr]
    port = sockets[0].getsockname()[1]
    try:
        yield {"base_url": f"http://127.0.0.1:{port}", "hits": hits, "state": state}
    finally:
        await runner.cleanup()
