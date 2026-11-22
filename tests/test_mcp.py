"""El servidor MCP responde con hora de actualización y el aviso de datos en vivo."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from mcp import Client

from metrotenerife.errors import AmbiguousStopError, OperatorNotFoundError, StopNotFoundError
from metrotenerife.operators import OperatorRegistry, TranviaOperator
from metrotenerife_mcp.server import build_server

FROZEN = datetime(2026, 11, 22, 14, 7, tzinfo=UTC)


async def test_tools_against_a_local_fake(api) -> None:
    server = build_server(
        base_url=api["base_url"], min_interval=0, cache_ttl=30, max_retries=0, clock=lambda: FROZEN
    )
    async with Client(server) as client:
        listed = await client.list_tools()
        assert {tool.name for tool in listed.tools} == {
            "buscar_parada",
            "proximos_tranvias",
            "estado_tranvias",
            "info_vehiculo",
            "info_lineas",
            "prevision_tranvias",
        }

        found = json.loads(
            (await client.call_tool("buscar_parada", {"consulta": "guimera"})).content[0].text
        )
        assert found["paradas"][0]["codigo"] == "GUI"
        assert "CC BY" in found["aviso"]

        live = json.loads(
            (await client.call_tool("proximos_tranvias", {"parada": "Intercambiador", "linea": 1}))
            .content[0]
            .text
        )
        assert live["aviso"].startswith("Datos en vivo")
        assert live["actualizacion_fuente"] == "2026-11-22T14:06:54+00:00"
        assert live["llegadas"][0]["minutos"] == 11
        assert live["llegadas"][0]["destino"] == "La Trinidad"
        assert live["llegadas"][0]["ocupacion_cruda"] == 28
        assert live["llegadas"][0]["ocupacion_porcentaje"] == 33
        assert live["llegadas"][0]["ocupacion_fresca"] is True
        assert live["llegadas"][0]["vehiculo"] == 102
        assert live["llegadas"][0]["posicion"]["proxima_parada_codigo"] == "FUN"
        assert live["parada"]["codigo"] == "INT"

        ambiguous = json.loads(
            (await client.call_tool("proximos_tranvias", {"parada": "hospital"})).content[0].text
        )
        assert ambiguous["ambiguo"] is True
        assert {stop["codigo"] for stop in ambiguous["paradas"]} == {"CAN", "HOS"}

        missing = await client.call_tool("proximos_tranvias", {"parada": "no-existe"})
        assert missing.is_error

        state = json.loads(
            (await client.call_tool("estado_tranvias", {"linea": 2})).content[0].text
        )
        assert state["obtenido_a"]
        assert state["tranvias"][0]["destino"] == "Tíncer"
        assert state["tranvias"][0]["lat"] == 28.448912
        assert state["tranvias"][0]["ocupacion_fresca"] is False
        assert state["tranvias"][0]["ocupacion_porcentaje"] is None
        assert state["tranvias"][0]["vehiculo"] is None
        assert state["tranvias"][0]["orden"] == 5

        found_vehicle = json.loads(
            (await client.call_tool("info_vehiculo", {"numero": 102})).content[0].text
        )
        assert found_vehicle["estado"] == "en_servicio"
        assert found_vehicle["servicio"] == "405"
        assert found_vehicle["ocupacion_fresca"] is True
        old_vehicle = json.loads(
            (await client.call_tool("info_vehiculo", {"numero": 88})).content[0].text
        )
        assert old_vehicle["estado"] == "dato_antiguo"
        assert old_vehicle["servicio"] is None
        unknown_vehicle = await client.call_tool("info_vehiculo", {"numero": 0})
        assert unknown_vehicle.is_error

        forecast = json.loads(
            (
                await client.call_tool(
                    "prevision_tranvias",
                    {
                        "parada": "Gracia",
                        "sentido": 1,
                        "desde": "2026-11-23T07:50:00",
                        "minutos": 20,
                    },
                )
            )
            .content[0]
            .text
        )
        assert forecast["mezclado_con_en_vivo"] is False
        assert [item["hora"][11:16] for item in forecast["pasos"]] == [
            "07:50",
            "07:55",
            "08:00",
            "08:05",
        ]
        assert forecast["pasos"][0]["tipo"] == "previsto"
        assert forecast["pasos"][0]["destino"] == "La Trinidad"

        info = json.loads((await client.call_tool("info_lineas", {})).content[0].text)
        assert [line["linea"] for line in info["lineas"]] == [1, 2]
        assert "Cabildo" in info["atribucion"]["publisher"]
        assert info["lineas"][0]["sentidos"][0]["paradas"][0]["codigo"] == "INT"

        unknown = await client.call_tool("info_lineas", {"operador": "titsa"})
        assert unknown.is_error
        assert "titsa" in unknown.content[0].text


def test_registry_is_the_extension_point() -> None:
    registry = OperatorRegistry()

    class _Later:
        id = "titsa"
        name = "TITSA"

    registry.register(_Later())  # type: ignore[arg-type]
    assert registry.available() == ["titsa"]
    with pytest.raises(OperatorNotFoundError):
        registry.get("tranvia")


def test_resolve_stop_is_exact_or_ambiguous() -> None:
    operator = TranviaOperator(client=None)  # type: ignore[arg-type]
    assert operator.resolve_stop("weyler").code == "WEY"
    assert operator.resolve_stop("01").code == "INT"
    try:
        operator.resolve_stop("hospital")
    except AmbiguousStopError as err:
        assert {stop.code for stop in err.matches} == {"CAN", "HOS"}  # type: ignore[attr-defined]
    else:
        raise AssertionError("hospital debería ser ambiguo")
    try:
        operator.resolve_stop("ninguna parada")
    except StopNotFoundError:
        return
    raise AssertionError("la consulta no debería resolver una parada")
