"""Texto JSON que devuelven las herramientas del servidor MCP.

La demo local usa estas mismas funciones, así que el navegador enseña
exactamente lo que recibiría un agente.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .forecast import Passage, load_schedule
from .models import Arrival, Stop, Vehicle, VehiclePosition, direction_label
from .occupancy import OCCUPANCY_MEANING, occupancy_texts
from .operators import AVISO_CATALOGO, AVISO_EN_VIVO, VehicleQuery


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
        "vehiculo": arrival.vehicle_id,
        "orden_parada": arrival.order,
        "posicion": position_payload(arrival.position),
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


def position_payload(position: VehiclePosition | None) -> dict[str, Any] | None:
    if position is None:
        return None
    return {
        "lat": position.lat,
        "lon": position.lon,
        "proxima_parada": position.next_stop_name,
        "proxima_parada_codigo": position.next_stop_code,
        "minutos_proxima_parada": position.minutes_to_next,
        "orden": position.order,
    }


def vehicle_state_payload(vehicle: Vehicle) -> dict[str, Any]:
    """Posición en vivo. El número de vehículo es null si no hay fila reciente."""
    updated = vehicle.occupancy_updated_at
    return {
        "servicio": vehicle.service,
        "vehiculo": vehicle.vehicle_id,
        "linea": vehicle.line,
        "sentido": vehicle.direction,
        "sentido_etiqueta": direction_label(vehicle.line, vehicle.direction),
        "destino": vehicle.destination_name,
        "destino_codigo": vehicle.destination_code,
        "proxima_parada": vehicle.next_stop_name,
        "proxima_parada_codigo": vehicle.next_stop_code,
        "minutos_proxima_parada": vehicle.minutes_to_next,
        "orden": vehicle.order,
        "lat": vehicle.lat,
        "lon": vehicle.lon,
        "ocupacion_cruda": vehicle.occupancy_raw,
        "ocupacion_porcentaje": vehicle.occupancy_percent,
        "ocupacion_muy_alta": vehicle.occupancy_high,
        "ocupacion_fresca": vehicle.occupancy_percent is not None,
        "ocupacion_actualizada": updated.isoformat() if updated else None,
        "ocupacion_descartada": vehicle.occupancy_discarded,
        "ocupacion_significado": OCCUPANCY_MEANING,
    }


def vehicle_query_payload(query: VehicleQuery) -> dict[str, Any]:
    """Lo que devuelve `info_vehiculo` y el buscador de la demo."""
    vehicle = query.vehicle
    return {
        "aviso": AVISO_EN_VIVO,
        "numero": query.number,
        "estado": query.state,
        "mensaje": query.message,
        "obtenido_a": query.fetched_at.isoformat(),
        "ocupacion_disponible": query.occupancy_available,
        "posicion_disponible": query.position_available,
        "servicio": query.service,
        "vehiculo": query.number if query.state in {"en_servicio", "sin_posicion"} else None,
        "linea": vehicle.line if vehicle else None,
        "sentido": vehicle.direction if vehicle else None,
        "sentido_etiqueta": (direction_label(vehicle.line, vehicle.direction) if vehicle else None),
        "destino": vehicle.destination_name if vehicle else None,
        "destino_codigo": vehicle.destination_code if vehicle else None,
        "lat": vehicle.lat if vehicle else None,
        "lon": vehicle.lon if vehicle else None,
        "proxima_parada": vehicle.next_stop_name if vehicle else None,
        "proxima_parada_codigo": vehicle.next_stop_code if vehicle else None,
        "minutos_proxima_parada": vehicle.minutes_to_next if vehicle else None,
        "orden": vehicle.order if vehicle else None,
        "ocupacion_cruda": query.occupancy_raw if query.occupancy_fresh else None,
        "ocupacion_porcentaje": query.occupancy_percent if query.occupancy_fresh else None,
        "ocupacion_muy_alta": query.occupancy_high if query.occupancy_fresh else False,
        "ocupacion_fresca": query.occupancy_fresh,
        "ocupacion_actualizada": (
            query.occupancy_updated_at.isoformat() if query.occupancy_updated_at else None
        ),
        "fila_antigua": (query.stale_updated_at.isoformat() if query.stale_updated_at else None),
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


def passage_payload(passage: Passage) -> dict[str, Any]:
    return {
        "hora": passage.at.isoformat(),
        "linea": passage.line,
        "sentido": passage.direction,
        "sentido_etiqueta": direction_label(passage.line, passage.direction),
        "destino": passage.destination_name,
        "destino_codigo": passage.destination_code,
        "tipo": passage.kind,
        "intervalo_minutos": passage.headway_minutes,
        "segundos_desde_cabecera": passage.travel_seconds,
        "servicio": passage.service,
    }


def forecast_payload(
    *,
    operator_id: str,
    stop: Stop,
    passages: list[Passage],
    start: datetime,
    end: datetime,
    mixed: bool,
    note: str,
) -> dict[str, Any]:
    """El objeto de `prevision_tranvias` y de la sección «Próximas horas»."""
    table = load_schedule().payload
    return {
        "aviso": note,
        "operador": operator_id,
        "parada": stop_payload(stop),
        "desde": start.isoformat(),
        "hasta": end.isoformat(),
        "mezclado_con_en_vivo": mixed,
        "mensaje": None if passages else "No hay pasos previstos en esa ventana.",
        "pasos": [passage_payload(passage) for passage in passages],
        "limitaciones": [
            table.get("calendar_note"),
            table.get("spacing_note"),
            table.get("service_hours_note"),
            table.get("holiday_note"),
        ],
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
