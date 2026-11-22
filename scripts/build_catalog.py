#!/usr/bin/env python3
"""Genera el catálogo estático de paradas y líneas a partir del GTFS oficial.

El feed del Cabildo (vigencia 2024-09-08 a 2025-07-15) está caducado y solo se
usa como catálogo: nombres, coordenadas y orden de paradas. No se copian
frecuencias ni horarios. Los nombres recuperan tildes que el CSV perdió.

Uso:
    python scripts/build_catalog.py ruta/google_transit.zip
"""

from __future__ import annotations

import csv
import io
import json
import sys
import zipfile
from pathlib import Path

# Nombres visibles. El GTFS escribe «Senor», «Espana» y «Jeronimo» sin tilde.
DISPLAY_NAMES = {
    "INT": "Intercambiador",
    "FUN": "Fundación",
    "GUI": "Teatro Guimerá",
    "WEY": "Weyler",
    "PAZ": "La Paz",
    "ZUR": "Puente Zurita",
    "CRS": "Cruz del Señor",
    "CON": "Conservatorio",
    "CHI": "Chimisay",
    "PPE": "Príncipes de España",
    "CAN": "Hospital La Candelaria",
    "TAC": "Taco",
    "CAR": "El Cardonal",
    "HOS": "Hospital Universitario",
    "MAN": "Las Mantecas",
    "GUA": "Campus Guajara",
    "GRA": "Gracia",
    "MCI": "Museo de la Ciencia",
    "CPI": "Cruz de Piedra",
    "ANC": "Padre Anchieta",
    "TRI": "La Trinidad",
    "CUE": "La Cuesta",
    "ING": "Ingenieros",
    "JER": "San Jerónimo",
    "TIN": "Tíncer",
}

# Viaje GTFS representativo -> (línea, sentido de TranvíaOnline).
# El direction_id del GTFS no coincide con el sentido de TranvíaOnline.
TRIP_TO_DIRECTION = {
    "IT": (1, 1),
    "TI": (1, 2),
    "TL": (2, 1),
    "LT": (2, 2),
}

DESTINATION_NAMES = {
    "TRI": "La Trinidad",
    "INT": "Intercambiador",
    "CUE": "La Cuesta",
    "TIN": "Tíncer",
}

LINE_META = {
    1: {
        "code": "L1",
        "name": "Línea 1",
        "description": "Santa Cruz – La Laguna",
    },
    2: {
        "code": "L2",
        "name": "Línea 2",
        "description": "La Cuesta – Tíncer",
    },
}

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src" / "metrotenerife" / "data" / "catalog.json"


def _read_zip_csv(archive: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    raw = archive.read(name).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(raw)))


def _online_code(stop_url: str) -> str:
    return stop_url.rstrip("/").rsplit("/", 1)[-1].strip().upper()


def _clock_seconds(value: str) -> int:
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    return hours * 3600 + minutes * 60 + seconds


def build(gtfs_zip: Path) -> dict[str, object]:
    with zipfile.ZipFile(gtfs_zip) as archive:
        stops_rows = _read_zip_csv(archive, "stops.txt")
        stop_times = _read_zip_csv(archive, "stop_times.txt")
        calendar = _read_zip_csv(archive, "calendar.txt")

    code_by_gtfs: dict[str, str] = {}
    stops: list[dict[str, object]] = []
    for row in stops_rows:
        code = _online_code(row["stop_url"])
        if code not in DISPLAY_NAMES:
            raise SystemExit(f"Parada GTFS {row['stop_id']} ({code}) sin nombre definido")
        code_by_gtfs[row["stop_id"]] = code
        description = (row.get("stop_desc") or "").strip()
        description = description.replace("Linea", "Línea")
        stops.append(
            {
                "code": code,
                "gtfs_id": row["stop_id"],
                "name": DISPLAY_NAMES[code],
                "description": description or None,
                "lat": float(row["stop_lat"]),
                "lon": float(row["stop_lon"]),
                "wheelchair": row.get("wheelchair_boarding") == "1",
            }
        )

    sequences: dict[str, list[tuple[str, int]]] = {}
    for row in sorted(stop_times, key=lambda item: (item["trip_id"], int(item["stop_sequence"]))):
        trip_id = row["trip_id"]
        if trip_id not in TRIP_TO_DIRECTION:
            continue
        sequences.setdefault(trip_id, []).append(
            (code_by_gtfs[row["stop_id"]], _clock_seconds(row["arrival_time"]))
        )

    directions: list[dict[str, object]] = []
    for trip_id, (line, direction) in TRIP_TO_DIRECTION.items():
        timed = sequences[trip_id]
        codes = [code for code, _moment in timed]
        segments = [timed[index + 1][1] - timed[index][1] for index in range(len(timed) - 1)]
        if any(segment < 0 for segment in segments):
            raise SystemExit(f"Tiempos negativos en el viaje {trip_id}")
        destination = codes[-1]
        directions.append(
            {
                "line": line,
                "direction": direction,
                "destination_code": destination,
                "destination_name": DESTINATION_NAMES[destination],
                "stop_codes": codes,
                "segment_seconds": segments,
                "gtfs_trip_id": trip_id,
            }
        )
    directions.sort(key=lambda item: (int(item["line"]), int(item["direction"])))

    lines_by_code: dict[str, set[int]] = {stop["code"]: set() for stop in stops}  # type: ignore[index]
    for direction in directions:
        for code in direction["stop_codes"]:  # type: ignore[union-attr]
            lines_by_code[str(code)].add(int(direction["line"]))
    for stop in stops:
        stop["lines"] = sorted(lines_by_code[str(stop["code"])])

    feed_start = min(row["start_date"] for row in calendar)
    feed_end = max(row["end_date"] for row in calendar)

    return {
        "version": 1,
        "attribution": {
            "title": "GTFS Metropolitano de Tenerife",
            "publisher": "Cabildo Insular de Tenerife / Metropolitano de Tenerife",
            "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "sources": [
                "https://datos.tenerife.es/ckan/dataset/4b83e018-37d9-40a6-b6d1-1df2b91c8117",
                "https://metrotenerife.com/transit/google_transit.zip",
            ],
            "feed_start": feed_start,
            "feed_end": feed_end,
            "derived_on": "2026-11-22",
            "note": (
                "Catálogo derivado (paradas, coordenadas, líneas, orden y minutos "
                "entre paradas consecutivas). Esos minutos solo sirven para estimar "
                "un tranvía que la API no anuncia; no son un horario. "
                "Se han restituido tildes que el CSV oficial omite. "
                "El feed está caducado. Los sentidos son los de TranvíaOnline."
            ),
        },
        "lines": [
            {
                **LINE_META[line],
                "line": line,
                "directions": [item for item in directions if item["line"] == line],
            }
            for line in (1, 2)
        ],
        "stops": stops,
    }


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit("Uso: python scripts/build_catalog.py ruta/google_transit.zip")
    catalog = build(Path(argv[1]))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    stops = catalog["stops"]
    print(f"Escrito {OUTPUT} ({len(stops)} paradas)")  # type: ignore[arg-type]


if __name__ == "__main__":
    main(sys.argv)
