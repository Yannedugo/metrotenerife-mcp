"""Texto JSON que devuelven las herramientas del servidor MCP.

La demo local usa estas mismas funciones, así que el navegador enseña
exactamente lo que recibiría un agente.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from metrotenerife.models import Arrival, Stop, direction_label
from metrotenerife.occupancy import OCCUPANCY_MEANING, occupancy_texts
from metrotenerife.operators import AVISO_CATALOGO, AVISO_EN_VIVO


def stop_payload(stop: Stop) -> dict[str, Any]:
    return {
        "codigo": stop.code,
        "nombre": stop.name,
        "lat": stop.lat,
        "lon": stop.lon,
        "lineas": list(stop.lines),
        "gtfs_id": stop.gtfs_id,
        "descripcion": stop.description,
    }


def arrival_payload(arrival: Arrival) -> dict[str, Any]:
    return {
        "linea": arrival.line,
        "sentido": arrival.direction,
        "sentido_etiqueta": direction_label(arrival.line, arrival.direction),
        "destino": arrival.destination_name,
        "destino_codigo": arrival.destination_code,
        "minutos": arrival.minutes,
        "llegando": arrival.minutes == 0,
        "llegada_estimada": arrival.estimated_arrival.isoformat(),
        "servicio": arrival.service,
        "actualizado": arrival.updated_at.isoformat(),
        "aproximado": arrival.approximate,
        "estimado": arrival.estimated,
        "origen": arrival.origin,
        "ocupacion_cruda": arrival.occupancy_raw if arrival.occupancy_fresh else None,
        "ocupacion_porcentaje": arrival.occupancy_percent if arrival.occupancy_fresh else None,
        "ocupacion_fresca": arrival.occupancy_fresh,
        "ocupacion_muy_alta": arrival.occupancy_high if arrival.occupancy_fresh else False,
        "ocupacion_texto": _occupancy_label(arrival)[0],
        "ocupacion_aviso": _occupancy_label(arrival)[1],
        "ocupacion_actualizada": (
            arrival.occupancy_updated_at.isoformat() if arrival.occupancy_updated_at else None
        ),
        "ocupacion_significado": OCCUPANCY_MEANING,
    }


def _occupancy_label(arrival: Arrival) -> tuple[str | None, str | None]:
    if not arrival.occupancy_fresh or arrival.occupancy_raw is None:
        return None, None
    text, warning = occupancy_texts(arrival.occupancy_raw)
    return text or None, warning or None


def proximos_payload(
    *,
    operator_id: str,
    stop: Stop,
    arrivals: list[Arrival],
    fetched_at: datetime,
    line: int | None,
    direction: int | None,
    destination: str | None,
    per_direction: int = 3,
    notes: list[dict[str, object]] | None = None,
) -> dict[str, Any]:
    """El objeto que serializa la herramienta `proximos_tranvias`."""
    updated = [arrival.updated_at for arrival in arrivals if not arrival.estimated]
    return {
        "aviso": AVISO_EN_VIVO,
        "operador": operator_id,
        "obtenido_a": fetched_at.isoformat(),
        "actualizacion_fuente": max(updated).isoformat() if updated else None,
        "parada": stop_payload(stop),
        "filtros": {"linea": line, "sentido": direction, "destino": destination},
        "por_sentido": per_direction,
        "mensaje": None if arrivals else "No hay tranvías anunciados con ese filtro.",
        "llegadas": [arrival_payload(arrival) for arrival in arrivals],
        "notas_estimacion": notes or [],
    }


def ambiguous_payload(
    operator_id: str, query: str, matches: list[Stop], message: str
) -> dict[str, Any]:
    return {
        "aviso": AVISO_CATALOGO,
        "operador": operator_id,
        "ambiguo": True,
        "consulta": query,
        "mensaje": message,
        "paradas": [stop_payload(stop) for stop in matches],
    }
