"""Normalización oficial de CARGA y estimación del tercer tranvía."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from metrotenerife.catalog import load_catalog
from metrotenerife.client import parse_arrivals, parse_vehicles
from metrotenerife.estimate import limit_per_direction
from metrotenerife.models import Vehicle
from metrotenerife.occupancy import normalize_carga, occupancy_texts
from metrotenerife.operators import compose_board

NOW = datetime(2026, 11, 22, 14, 7, tzinfo=UTC)


# Réplica literal del ternario de getCargaNormalizada.
def _reference(raw: int) -> int:
    return (
        3
        if raw < 5
        else 7
        if raw < 8
        else 10
        if raw < 11
        else 14
        if raw < 14
        else 18
        if raw < 17
        else 22
        if raw < 20
        else 25
        if raw < 23
        else 29
        if raw < 26
        else 33
        if raw < 29
        else 36
        if raw < 32
        else 40
        if raw < 35
        else 44
        if raw < 38
        else 48
        if raw < 41
        else 51
        if raw < 44
        else 55
        if raw < 47
        else 59
        if raw < 50
        else 62
        if raw < 53
        else 66
        if raw < 56
        else 70
        if raw < 59
        else 74
        if raw < 62
        else 77
        if raw < 65
        else 81
        if raw < 68
        else 85
        if raw < 71
        else 89
        if raw < 74
        else 92
        if raw < 77
        else 96
        if raw < 80
        else 100
    )


def test_normalize_carga_matches_the_official_table() -> None:
    boundaries = {
        0: 3,
        4: 3,
        5: 7,
        7: 7,
        8: 10,
        10: 10,
        11: 14,
        13: 14,
        14: 18,
        16: 18,
        17: 22,
        19: 22,
        20: 25,
        22: 25,
        23: 29,
        25: 29,
        26: 33,
        28: 33,
        29: 36,
        31: 36,
        32: 40,
        34: 40,
        35: 44,
        37: 44,
        38: 48,
        40: 48,
        41: 51,
        43: 51,
        44: 55,
        46: 55,
        47: 59,
        49: 59,
        50: 62,
        52: 62,
        53: 66,
        55: 66,
        56: 70,
        58: 70,
        59: 74,
        61: 74,
        62: 77,
        64: 77,
        65: 81,
        67: 81,
        68: 85,
        70: 85,
        71: 89,
        73: 89,
        74: 92,
        76: 92,
        77: 96,
        79: 96,
        80: 100,
        81: 100,
        100: 100,
    }
    for raw, shown in boundaries.items():
        assert normalize_carga(raw) == shown == _reference(raw)
    for raw in range(0, 121):
        assert normalize_carga(raw) == _reference(raw)
    text, warning = occupancy_texts(28)
    assert text == "OCUPACIÓN: 33%"
    assert warning == ""
    text, warning = occupancy_texts(80)
    assert text == ""
    assert "MUY ALTA (100%)" in warning


def test_real_panel_has_exactly_two_arrivals_per_direction(fixture) -> None:
    arrivals = parse_arrivals(fixture("info_panel_all.json"))
    groups = Counter((item.stop_code, item.line, item.direction) for item in arrivals)
    assert arrivals
    assert set(groups.values()) == {2}


def test_third_tram_is_estimated_from_an_upstream_vehicle(fixture) -> None:
    catalog = load_catalog()
    assert catalog.direction_of(1, 1).segment_seconds[0] == 120
    official = [
        item for item in parse_arrivals(fixture("info_panel_int.json")) if item.stop_code == "INT"
    ]
    upstream = Vehicle(
        service="501",
        lat=28.45,
        lon=-16.25,
        line=1,
        direction=1,
        minutes_to_next=20,
        next_stop_code="INT",
        next_stop_name="Intercambiador",
        destination_code="TRI",
        destination_name="La Trinidad",
        vehicle_id=77,
    )
    already_passed = Vehicle(
        service="502",
        lat=28.46,
        lon=-16.25,
        line=1,
        direction=1,
        minutes_to_next=1,
        next_stop_code="GUI",
        next_stop_name="Teatro Guimerá",
        destination_code="TRI",
        destination_name="La Trinidad",
    )
    turning = Vehicle(
        service="503",
        lat=28.48,
        lon=-16.31,
        line=1,
        direction=2,
        minutes_to_next=0,
        next_stop_code="TRI",
        next_stop_name="La Trinidad",
        destination_code="INT",
        destination_name="Intercambiador",
    )
    board, notes = limit_per_direction(
        official,
        [upstream, already_passed, turning],
        catalog,
        per_direction=3,
        now=NOW,
    )
    assert [item.service for item in board] == ["405", "407", "501"]
    assert board[2].estimated is True
    assert board[2].origin == "estimado"
    assert board[2].minutes == 20
    assert board[2].vehicle_id == 77
    assert notes == []
    composed, _composed_notes = compose_board(
        official,
        [upstream, already_passed, turning],
        catalog,
        per_direction=3,
        now=NOW,
    )
    assert composed[2].position is not None
    assert composed[2].position.next_stop_code == "INT"
    assert composed[2].position.lat == 28.45
    assert composed[0].position is None

    only_official, missing = limit_per_direction(
        official, [already_passed, turning], catalog, per_direction=3, now=NOW
    )
    assert [item.estimated for item in only_official] == [False, False]
    assert missing and "cabecera" in str(missing[0]["motivo"])


def test_vehicle_fixture_does_not_invent_a_third_at_intercambiador(fixture) -> None:
    catalog = load_catalog()
    official = parse_arrivals(fixture("info_panel_int.json"))
    vehicles = parse_vehicles(fixture("vehicle_location.json"))
    board, notes = limit_per_direction(official, vehicles, catalog, per_direction=3, now=NOW)
    assert len(board) == 2
    assert notes
