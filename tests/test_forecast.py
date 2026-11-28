"""Previsión teórica. No llama a TranvíaOnline salvo el caso que mezcla datos en vivo."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from aiohttp.test_utils import TestClient, TestServer

from metrotenerife.catalog import load_catalog
from metrotenerife.forecast import load_schedule, merge_live, theoretical_passages
from metrotenerife.models import Arrival
from metrotenerife_demo.app import create_app

CANARY = ZoneInfo("Atlantic/Canary")
FROZEN = datetime(2026, 11, 22, 14, 7, tzinfo=UTC)


def test_weekday_morning_at_gracia_is_every_five_minutes() -> None:
    catalog = load_catalog()
    start = datetime(2026, 11, 23, 7, 50, tzinfo=CANARY)
    end = start.replace(hour=8, minute=10)
    passages = theoretical_passages(catalog, "GRA", start=start, end=end, direction=1, line=1)
    assert [item.at.strftime("%H:%M") for item in passages] == ["07:50", "07:55", "08:00", "08:05"]
    assert {item.kind for item in passages} == {"previsto"}
    assert {item.destination_code for item in passages} == {"TRI"}
    assert passages[0].headway_minutes == 5
    assert passages[0].travel_seconds == 1800


def test_sunday_and_holiday_use_the_wider_interval() -> None:
    catalog = load_catalog()
    start = datetime(2026, 11, 22, 7, 20, tzinfo=CANARY)
    end = datetime(2026, 11, 22, 8, 10, tzinfo=CANARY)
    sunday = theoretical_passages(catalog, "GRA", start=start, end=end, direction=1, line=1)
    assert [item.at.strftime("%H:%M") for item in sunday] == ["07:30", "08:00"]
    assert sunday[0].headway_minutes == 30

    holiday_start = datetime(2026, 1, 1, 7, 20, tzinfo=CANARY)
    holiday_end = datetime(2026, 1, 1, 8, 10, tzinfo=CANARY)
    holiday = theoretical_passages(
        catalog, "GRA", start=holiday_start, end=holiday_end, direction=1, line=1
    )
    assert [item.at.strftime("%H:%M") for item in holiday] == ["07:30", "08:00"]


def test_weekday_night_and_line_two_overnight_have_no_service() -> None:
    catalog = load_catalog()
    night = theoretical_passages(
        catalog,
        "INT",
        start=datetime(2026, 11, 23, 3, 0, tzinfo=CANARY),
        end=datetime(2026, 11, 23, 4, 0, tzinfo=CANARY),
        direction=1,
        line=1,
    )
    assert night == []
    saturday_line_two = theoretical_passages(
        catalog,
        "TIN",
        start=datetime(2026, 11, 21, 2, 0, tzinfo=CANARY),
        end=datetime(2026, 11, 21, 3, 0, tzinfo=CANARY),
        direction=1,
        line=2,
    )
    assert saturday_line_two == []


def test_summer_band_uses_seven_and_a_half_minutes() -> None:
    catalog = load_catalog()
    passages = theoretical_passages(
        catalog,
        "INT",
        start=datetime(2026, 7, 2, 20, 0, tzinfo=CANARY),
        end=datetime(2026, 7, 2, 20, 16, tzinfo=CANARY),
        direction=1,
        line=1,
    )
    assert [item.at.strftime("%H:%M:%S") for item in passages] == [
        "20:00:00",
        "20:07:30",
        "20:15:00",
    ]
    assert passages[0].headway_minutes == 7.5


def test_season_boundary_changes_the_weekday_headway() -> None:
    schedule = load_schedule()
    from datetime import date

    assert schedule.season_of(date(2026, 9, 7)) == "verano_1"
    assert schedule.season_of(date(2026, 9, 8)) == "invierno"
    assert schedule.headway(datetime(2026, 9, 7, 7, 30, tzinfo=CANARY), 1) == 6
    assert schedule.headway(datetime(2026, 9, 8, 7, 30, tzinfo=CANARY), 1) == 5


def test_bands_cover_the_day_without_gaps() -> None:
    bands = load_schedule().payload["bands"]
    covered = []
    for band in bands:
        covered.append((band["from_hour"], band["to_hour"]))
    assert covered[0][0] == 0
    assert covered[-1][1] == 24
    for previous, current in zip(covered, covered[1:], strict=False):
        assert previous[1] == current[0]


def _live_arrival(at: datetime, *, service: str = "405") -> Arrival:
    return Arrival(
        service=service,
        stop_code="GRA",
        stop_name="Gracia",
        destination_code="TRI",
        destination_name="La Trinidad",
        line=1,
        direction=1,
        minutes=0,
        updated_at=at,
    )


def test_live_passage_replaces_at_most_one_forecast() -> None:
    """Intervalo de 5 min, previstos 08:00 y 08:05, real 08:02:30: queda un previsto."""
    catalog = load_catalog()
    start = datetime(2026, 11, 23, 7, 58, tzinfo=CANARY)
    end = datetime(2026, 11, 23, 8, 8, tzinfo=CANARY)
    forecast = theoretical_passages(catalog, "GRA", start=start, end=end, direction=1, line=1)
    assert [item.at.strftime("%H:%M") for item in forecast] == ["08:00", "08:05"]

    # A la misma distancia de los dos, cae el anterior: un tranvía con retraso
    # es más normal que uno adelantado.
    real = datetime(2026, 11, 23, 8, 2, 30, tzinfo=CANARY)
    merged = merge_live(forecast, [_live_arrival(real)], start=start, end=end)
    assert [(item.at.strftime("%H:%M:%S"), item.kind) for item in merged] == [
        ("08:02:30", "en_vivo"),
        ("08:05:00", "previsto"),
    ]

    two_live = [_live_arrival(real), _live_arrival(real, service="406")]
    merged = merge_live(forecast, two_live, start=start, end=end)
    assert [item.kind for item in merged] == ["en_vivo", "en_vivo"]


async def test_demo_forecast_is_theoretical_tomorrow_and_mixes_live_now(api) -> None:
    app = create_app(
        base_url=api["base_url"], min_interval=0, cache_ttl=30, max_retries=0, clock=lambda: FROZEN
    )
    async with TestClient(TestServer(app)) as http:
        later = await http.get(
            "/api/prevision",
            params={
                "parada": "Gracia",
                "sentido": "1",
                "desde": "2026-11-23T07:50:00",
                "minutos": "20",
            },
        )
        body = await later.json()
        live = await http.get(
            "/api/prevision", params={"parada": "INT", "sentido": "1", "minutos": "40"}
        )
        mixed = await live.json()
    assert later.status == 200
    assert body["mezclado_con_en_vivo"] is False
    assert [item["hora"][11:16] for item in body["pasos"]] == ["07:50", "07:55", "08:00", "08:05"]
    assert {item["tipo"] for item in body["pasos"]} == {"previsto"}
    assert "No es un horario oficial" in body["aviso"]
    assert mixed["mezclado_con_en_vivo"] is True
    kinds = {item["tipo"] for item in mixed["pasos"]}
    assert "en_vivo" in kinds
    assert "previsto" in kinds
    assert any(item["servicio"] == "405" and item["tipo"] == "en_vivo" for item in mixed["pasos"])
