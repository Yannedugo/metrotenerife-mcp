"""Catálogo estático y búsqueda sin red."""

from datetime import datetime

from metrotenerife import load_catalog
from metrotenerife.client import parse_arrivals
from metrotenerife.models import direction_label


def test_catalog_covers_both_lines_and_attributes_the_cabildo() -> None:
    catalog = load_catalog()
    assert len(catalog.stops) == 25
    codes = {stop.code for stop in catalog.stops}
    assert "INT" in codes and "TIN" in codes and "CAR" in codes
    cardonal = catalog.get("CAR")
    assert cardonal is not None
    assert cardonal.lines == (1, 2)
    assert catalog.get("01") is not None
    assert catalog.get("01").code == "INT"  # type: ignore[union-attr]
    attribution = catalog.attribution
    assert attribution["license"] == "CC BY 4.0"
    assert "Cabildo" in str(attribution["publisher"])
    assert "20250715" in str(attribution["feed_end"])
    line1 = catalog.line(1)
    assert line1 is not None
    outbound = line1.directions[0]
    assert outbound.direction == 1
    assert outbound.stop_codes[0] == "INT"
    assert outbound.stop_codes[-1] == "TRI"
    line2 = catalog.line(2)
    assert line2 is not None
    assert line2.directions[1].destination_code == "TIN"


def test_search_ignores_case_and_accents() -> None:
    catalog = load_catalog()
    assert [stop.code for stop in catalog.search("guimera")] == ["GUI"]
    assert [stop.code for stop in catalog.search("GUIMERÁ")] == ["GUI"]
    assert catalog.search("principe")[0].code == "PPE"
    assert catalog.search("TIN")[0].code == "TIN"
    hospitals = {stop.code for stop in catalog.search("hospital")}
    assert hospitals == {"CAN", "HOS"}
    assert catalog.search("   ") == []
    assert catalog.search("no-existe") == []


def test_direction_labels_match_the_usual_termini() -> None:
    assert direction_label(1, 1) == "Hacia La Trinidad"
    assert direction_label(1, 2) == "Hacia Intercambiador"
    assert direction_label(2, 1) == "Hacia La Cuesta"
    assert direction_label(2, 2) == "Hacia Tíncer"


def test_real_panel_example_parses_estimated_arrival(fixture) -> None:
    arrivals = parse_arrivals(fixture("info_panel_int.json"))
    first = arrivals[0]
    assert first.service == "405"
    assert first.stop_code == "INT"
    assert first.line == 1
    assert first.direction == 1
    assert first.minutes == 11
    assert first.updated_at == datetime.fromisoformat("2026-11-22T14:06:54+00:00")
    assert first.estimated_arrival == datetime.fromisoformat("2026-11-22T14:17:54+00:00")
