"""Cliente HTTP contra un servidor local que reproduce las respuestas grabadas."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import aiohttp
import pytest

from metrotenerife.client import (
    TranviaOnlineClient,
    filter_arrivals,
    merge_occupancy,
    parse_arrivals,
    parse_occupancy,
    parse_vehicles,
)
from metrotenerife.errors import HttpStatusError, ParseError, RequestTimeoutError, StopNotFoundError

FROZEN = datetime(2026, 11, 22, 14, 7, tzinfo=UTC)


def _client(api: dict, **kwargs: object) -> TranviaOnlineClient:
    options = {
        "base_url": api["base_url"],
        "min_interval": 0,
        "cache_ttl": 30,
        "user_agent": "metrotenerife-test",
    }
    options.update(kwargs)
    return TranviaOnlineClient(**options)  # type: ignore[arg-type]


async def test_panel_uses_user_agent_cache_and_sorts(api) -> None:
    sleeps: list[float] = []

    async def sleeper(seconds: float) -> None:
        sleeps.append(seconds)

    async with _client(api, sleeper=sleeper, min_interval=1) as client:
        first = await client.panel("int")
        second = await client.panel("INT")
    assert [item.minutes for item in first] == [11, 16]
    assert second[0].service == "405"
    assert api["hits"].count("INT") == 1
    assert sleeps == []


async def test_unknown_code_does_not_call_the_network(api) -> None:
    async with _client(api) as client:
        with pytest.raises(StopNotFoundError):
            await client.panel("no es una parada")
    assert api["hits"] == []


async def test_http_404_is_a_missing_stop_and_is_not_retried(api) -> None:
    async with _client(api, max_retries=2) as client:
        with pytest.raises(StopNotFoundError):
            await client.panel("ZZZ")
    assert api["hits"] == ["missing"]


async def test_malformed_json_raises_parse_error(api) -> None:
    async with _client(api, max_retries=0) as client:
        with pytest.raises(ParseError):
            await client.panel("BAD")


async def test_timeout_is_reported(api) -> None:
    async with _client(api, timeout=0.1, max_retries=0) as client:
        with pytest.raises(RequestTimeoutError):
            await client.panel("SLOW")


async def test_server_errors_backoff_then_succeed(api) -> None:
    sleeps: list[float] = []

    async def sleeper(seconds: float) -> None:
        sleeps.append(seconds)

    async with _client(api, max_retries=2, sleeper=sleeper) as client:
        arrivals = await client.panel("FLKY")
    assert arrivals[0].stop_code == "INT"
    assert api["hits"] == ["flaky", "flaky", "flaky"]
    assert sleeps == [0.0, 0.0]


async def test_retries_exhausted_raise_http_status(api) -> None:
    async with _client(api, max_retries=0) as client:
        with pytest.raises(HttpStatusError) as caught:
            await client.panel("FLKY")
    assert caught.value.status == 500


async def test_all_panels_group_stops(api) -> None:
    async with _client(api) as client:
        grouped = await client.panels()
    assert set(grouped) == {"INT", "CAR"}
    assert [item.minutes for item in grouped["CAR"]] == [2, 4, 9]


async def test_dict_shaped_payload_is_accepted() -> None:
    payload = {
        "INT": [
            {
                "service": "1",
                "stop": "INT",
                "destinationStop": "TRI",
                "route": "1",
                "direction": "1",
                "remainingMinutes": 3,
                "lastUpdateFormatted": "22/11/2026 14:06:54",
            }
        ]
    }
    arrivals = parse_arrivals(payload)
    assert arrivals[0].line == 1
    assert arrivals[0].updated_at.tzinfo is not None


async def test_broken_items_are_skipped_until_none_remain() -> None:
    payload = [
        {"service": "1", "stop": "INT"},
        {
            "service": "2",
            "stop": "INT",
            "destinationStop": "TRI",
            "route": 1,
            "direction": 1,
            "remainingMinutes": 1,
            "lastUpdate": 1795356414000,
        },
    ]
    assert len(parse_arrivals(payload)) == 1
    with pytest.raises(ParseError):
        parse_arrivals([{"hola": "no"}])
    with pytest.raises(ParseError):
        parse_arrivals({"inesperado": 1})


def test_occupancy_drops_stale_rows(fixture) -> None:
    vehicles = parse_vehicles(fixture("vehicle_location.json"))
    fresh, stale = parse_occupancy(
        fixture("carga_vehiculo.json"),
        now=FROZEN,
        max_age=timedelta(seconds=180),
    )
    assert set(fresh) == {"405"}
    assert fresh["405"].percent == 28
    assert fresh["405"].vehicle_id == 102
    assert "409" in stale and "999" in stale
    merged = {vehicle.service: merge_occupancy(vehicle, fresh, stale) for vehicle in vehicles}
    assert merged["405"].occupancy_percent == 28
    assert merged["409"].occupancy_percent is None
    assert merged["409"].occupancy_discarded is True


async def test_vehicles_keep_positions_if_occupancy_fails(api, monkeypatch) -> None:
    """Si la ocupación falla, las posiciones se devuelven igual."""
    async with _client(api, max_retries=0) as client:
        original = client._get_json

        async def flaky_get(path: str):
            if path == "/api/cargaVehiculo":
                raise HttpStatusError(503, path)
            return await original(path)

        monkeypatch.setattr(client, "_get_json", flaky_get)
        snapshot = await client.vehicles(now=FROZEN)
    assert snapshot.occupancy_available is False
    assert {vehicle.service for vehicle in snapshot.vehicles} == {"405", "409"}


def test_filter_by_line_direction_and_destination(fixture) -> None:
    arrivals = parse_arrivals(fixture("info_panel_car.json"))
    assert [item.line for item in filter_arrivals(arrivals, line=2)] == [2, 2]
    towards_tin = filter_arrivals(arrivals, destination="tincer")
    assert [item.destination_code for item in towards_tin] == ["TIN"]
    assert filter_arrivals(arrivals, direction=1)[0].destination_code in {"TRI", "CUE"}
    assert len(filter_arrivals(arrivals, lines=[1], direction=2)) == 0


async def test_session_is_not_closed_when_it_is_provided(api) -> None:
    async with aiohttp.ClientSession() as session:
        client = TranviaOnlineClient(session, base_url=api["base_url"], min_interval=0, cache_ttl=0)
        await client.panel("INT")
        await client.aclose()
        assert not session.closed
