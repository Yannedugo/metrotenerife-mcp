"""Cliente HTTP contra un servidor local que reproduce las respuestas grabadas."""

from __future__ import annotations

import ssl
from datetime import UTC, datetime, timedelta

import aiohttp
import pytest

from metrotenerife.catalog import load_catalog
from metrotenerife.client import (
    TranviaOnlineClient,
    default_ssl_context,
    filter_arrivals,
    merge_occupancy,
    parse_arrivals,
    parse_occupancy,
    parse_vehicles,
)
from metrotenerife.errors import (
    HttpStatusError,
    ParseError,
    RequestTimeoutError,
    StopNotFoundError,
    TransportError,
)
from metrotenerife.operators import label_arrival

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
    assert api["hits"].count("occupancy") == 1
    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(1, abs=0.05)


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
    assert api["hits"][:3] == ["flaky", "flaky", "flaky"]
    assert "occupancy" in api["hits"]
    assert sleeps == [0.0, 0.0]


async def test_retries_exhausted_raise_http_status(api) -> None:
    async with _client(api, max_retries=0) as client:
        with pytest.raises(HttpStatusError) as caught:
            await client.panel("FLKY")
    assert caught.value.status == 500


def test_real_all_panels_filter_by_stop_line_and_direction(fixture) -> None:
    """La captura real del 22/11/2026 agrupa y filtra por parada, línea y sentido."""
    catalog = load_catalog()
    arrivals = [
        label_arrival(item, catalog) for item in parse_arrivals(fixture("info_panel_all.json"))
    ]
    assert len(arrivals) == 100
    by_stop: dict[str, list] = {}
    for arrival in arrivals:
        by_stop.setdefault(arrival.stop_code, []).append(arrival)
    assert set(by_stop) == {stop.code for stop in catalog.stops}

    to_trinidad = filter_arrivals(by_stop["CAR"], line=1, direction=1)
    assert [item.minutes for item in to_trinidad] == [10, 20]
    assert {item.destination_name for item in to_trinidad} == {"La Trinidad"}
    assert to_trinidad[0].updated_at == datetime(2026, 11, 22, 14, 42, 30, tzinfo=UTC)

    to_tincer = filter_arrivals(by_stop["CAR"], line=2, direction=2)
    assert [item.minutes for item in to_tincer] == [8, 22]
    assert {item.destination_name for item in to_tincer} == {"Tíncer"}

    assert filter_arrivals(by_stop["INT"], line=1, direction=2) == []
    assert [item.minutes for item in filter_arrivals(by_stop["INT"], destination="trinidad")] == [
        10,
        20,
    ]

    arriving = filter_arrivals(by_stop["FUN"], line=1, direction=1)
    assert arriving[0].minutes == 0
    assert arriving[0].service == "408"


async def test_all_panels_group_stops(api) -> None:
    async with _client(api) as client:
        grouped = await client.panels()
    assert len(grouped) == 25
    assert [item.minutes for item in grouped["INT"]] == [10, 20]
    cardonal = filter_arrivals(grouped["CAR"], line=2, direction=2)
    assert [item.destination_code for item in cardonal] == ["TIN", "TIN"]
    assert [item.minutes for item in cardonal] == [8, 22]


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
    assert fresh["405"].raw == 28
    assert fresh["405"].vehicle_id == 102
    assert "409" in stale and "999" in stale
    merged = {vehicle.service: merge_occupancy(vehicle, fresh, stale) for vehicle in vehicles}
    assert merged["405"].occupancy_raw == 28
    assert merged["405"].occupancy_percent == 33
    assert merged["405"].occupancy_high is False
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


def test_ssl_context_keeps_verification_on() -> None:
    context = default_ssl_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.get_ca_certs()


async def test_connection_error_includes_the_real_cause() -> None:
    class _Boom:
        async def __aenter__(self):
            raise aiohttp.ClientConnectionError(
                "certificate verify failed: unable to get local issuer certificate"
            )

        async def __aexit__(self, *_exc: object) -> bool:
            return False

    class _Session:
        closed = False

        def get(self, *_args: object, **kwargs: object) -> _Boom:
            context = kwargs["ssl"]
            assert isinstance(context, ssl.SSLContext)
            assert context.verify_mode == ssl.CERT_REQUIRED
            return _Boom()

        async def close(self) -> None:
            self.closed = True

    client = TranviaOnlineClient(_Session(), min_interval=0, max_retries=0)  # type: ignore[arg-type]
    with pytest.raises(TransportError) as caught:
        await client.panel("INT")
    message = str(caught.value)
    assert "ClientConnectionError" in message
    assert "certificate verify failed" in message
    assert caught.value.cause_type == "ClientConnectionError"
