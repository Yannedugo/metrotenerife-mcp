"""Cliente asíncrono de TranvíaOnline.

La web oficial sondea cada pocos segundos. Este cliente no lo hace: caché corta,
una petición en vuelo y reintentos con espera solo ante 429 o 5xx. La API no es
oficial y no hay que redistribuir el JSON crudo.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp
import certifi

from metrotenerife.errors import (
    HttpStatusError,
    ParseError,
    RequestTimeoutError,
    StopNotFoundError,
    TransportError,
)
from metrotenerife.models import Arrival, Occupancy, Vehicle, VehicleSnapshot
from metrotenerife.occupancy import HIGH_CARGA, normalize_carga

logger = logging.getLogger(__name__)

# Claves con las que la fuente puede nombrar el número pintado en el tranvía.
# `service` no es ese número: es el servicio de la marcha.
_VEHICLE_ID_KEYS = ("VEHICULO", "vehiculo", "vehicleId", "numeroVehiculo")

USER_AGENT = (
    "metrotenerife/0.1.0 (+https://github.com/Yannedugo/metrotenerife-mcp; "
    "contacto: https://github.com/Yannedugo/metrotenerife-mcp/issues; "
    "uso personal, no oficial, sin ánimo de lucro)"
)
DEFAULT_BASE_URL = "https://tranviaonline.metrotenerife.com"
CANARY = ZoneInfo("Atlantic/Canary")
_STOP_CODE = re.compile(r"^[A-Z0-9]{2,4}$")
_LOCAL_TIME = "%d/%m/%Y %H:%M:%S"

Sleeper = Callable[[float], Awaitable[None]]
Clock = Callable[[], datetime]


def default_ssl_context() -> ssl.SSLContext:
    """Contexto que verifica el certificado con el almacén de certifi.

    El Python de python.org en macOS no trae raíces hasta que se ejecuta
    Install Certificates.command. certifi las incluye y la verificación sigue
    activa: no se usa CERT_NONE.
    """
    context = ssl.create_default_context(cafile=certifi.where())
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


class _TTLCache:
    def __init__(self, ttl: float) -> None:
        self._ttl = ttl
        self._items: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        item = self._items.get(key)
        if item is None:
            return None
        expires, value = item
        if expires <= asyncio.get_running_loop().time():
            self._items.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._items[key] = (asyncio.get_running_loop().time() + self._ttl, value)


class TranviaOnlineClient:
    """Consultas a los JSON de TranvíaOnline."""

    def __init__(
        self,
        session: aiohttp.ClientSession | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 12.0,
        cache_ttl: float = 20.0,
        min_interval: float = 1.0,
        max_retries: int = 2,
        user_agent: str = USER_AGENT,
        occupancy_max_age: float = 180.0,
        sleeper: Sleeper | None = None,
        clock: Clock | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._session = session
        self._owns_session = session is None
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._user_agent = user_agent
        self._occupancy_max_age = timedelta(seconds=occupancy_max_age)
        self._sleeper = sleeper or asyncio.sleep
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ssl = ssl_context or default_ssl_context()
        self._cache = _TTLCache(cache_ttl)
        self._lock = asyncio.Lock()
        self._last_request_at: float | None = None

    async def __aenter__(self) -> TranviaOnlineClient:
        self._ensure_session()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    def now(self) -> datetime:
        """Reloj de las consultas. Los tests pueden congelarlo."""
        return self._clock()

    async def aclose(self) -> None:
        """Cierra la sesión solo si la creó este cliente."""
        if self._owns_session and self._session is not None and not self._session.closed:
            await self._session.close()

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._timeout),
                connector=aiohttp.TCPConnector(ssl=self._ssl),
            )
            self._owns_session = True
        return self._session

    async def panel(self, stop_code: str) -> list[Arrival]:
        """Próximos tranvías anunciados en una parada, con ocupación si está fresca."""
        code = normalize_stop_code(stop_code)
        try:
            payload = await self._get_json(f"/api/infoStops/infoPanel/{code}")
        except HttpStatusError as err:
            if err.status == 404:
                raise StopNotFoundError(code) from err
            raise
        arrivals = parse_arrivals(payload, now=self._clock())
        return _sort_arrivals(await self._with_occupancy(arrivals))

    async def panels(self) -> dict[str, list[Arrival]]:
        """Próximos tranvías de todas las paradas, agrupados por código.

        La captura del 22/11/2026 es una lista plana con los mismos objetos
        que el panel de una parada. También se acepta un objeto cuyas listas
        tengan esa forma, por si el endpoint cambia el envoltorio.
        """
        payload = await self._get_json("/api/infoStops/infoPanel")
        arrivals = await self._with_occupancy(parse_arrivals(payload, now=self._clock()))
        grouped: dict[str, list[Arrival]] = {}
        for arrival in arrivals:
            grouped.setdefault(arrival.stop_code, []).append(arrival)
        return {code: _sort_arrivals(items) for code, items in grouped.items()}

    async def vehicles(self, *, now: datetime | None = None) -> VehicleSnapshot:
        """Posición de las unidades, con ocupación solo si el dato es reciente.

        Si la ocupación falla, se devuelven igual las posiciones.
        """
        moment = now or self._clock()
        locations = await self._get_json("/api/infoStops/vehicleLocation")
        vehicles = parse_vehicles(locations)
        fresh, stale, occupancy_available = await self._occupancy_index(moment)
        merged = tuple(merge_occupancy(vehicle, fresh, stale) for vehicle in vehicles)
        return VehicleSnapshot(
            vehicles=merged, fetched_at=moment, occupancy_available=occupancy_available
        )

    async def _with_occupancy(self, arrivals: list[Arrival]) -> list[Arrival]:
        fresh, stale, _available = await self._occupancy_index(self._clock())
        return [attach_occupancy(arrival, fresh, stale) for arrival in arrivals]

    async def occupancy_index(self, now: datetime | None = None) -> tuple[OccupancyIndex, bool]:
        """Filas recientes y filas viejas. El booleano dice si el endpoint respondió."""
        moment = now or self._clock()
        try:
            payload = await self._get_json("/api/cargaVehiculo")
        except (HttpStatusError, RequestTimeoutError, TransportError, ParseError):
            logger.warning("No se pudo leer la ocupación; se deja como desconocida")
            return OccupancyIndex(fresh={}, stale=()), False
        return classify_occupancy(payload, now=moment, max_age=self._occupancy_max_age), True

    async def _occupancy_index(self, now: datetime) -> tuple[dict[str, Occupancy], set[str], bool]:
        """Ocupación fresca, servicios con dato viejo y si el endpoint respondió."""
        index, available = await self.occupancy_index(now)
        if not available:
            return {}, set(), False
        fresh, stale = index.fresh, {item.service for item in index.stale}
        return fresh, stale, True

    async def _get_json(self, path: str) -> Any:
        cached = self._cache.get(path)
        if cached is not None:
            return cached
        async with self._lock:
            cached = self._cache.get(path)
            if cached is not None:
                return cached
            payload = await self._fetch_with_retries(path)
            self._cache.set(path, payload)
            return payload

    async def _fetch_with_retries(self, path: str) -> Any:
        last_error: HttpStatusError | RequestTimeoutError | None = None
        for attempt in range(self._max_retries + 1):
            if last_error is not None:
                await self._sleeper(self._backoff_seconds(attempt, last_error))
            await self._pace()
            try:
                return await self._fetch_once(path)
            except HttpStatusError as err:
                if not err.retryable or attempt == self._max_retries:
                    raise
                last_error = err
                logger.info("Reintento %s de %s tras HTTP %s", attempt + 1, path, err.status)
            except (RequestTimeoutError, TransportError) as err:
                if attempt == self._max_retries:
                    raise
                last_error = (
                    err
                    if isinstance(err, HttpStatusError | RequestTimeoutError)
                    else RequestTimeoutError(path)
                )
                logger.info("Reintento %s de %s tras un fallo de red", attempt + 1, path)
        raise RequestTimeoutError(path)

    async def _fetch_once(self, path: str) -> Any:
        session = self._ensure_session()
        url = f"{self._base_url}{path}"
        headers = {"User-Agent": self._user_agent, "Accept": "application/json"}
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        try:
            async with session.get(
                url, headers=headers, timeout=timeout, ssl=self._ssl
            ) as response:
                if response.status >= 400:
                    raise HttpStatusError(
                        response.status, path, retry_after=_retry_after(response.headers)
                    )
                try:
                    return await response.json(content_type=None)
                except (aiohttp.ContentTypeError, json.JSONDecodeError, TypeError) as err:
                    raise ParseError() from err
        except TimeoutError as err:
            logger.debug("Tiempo agotado al consultar %s", path, exc_info=err)
            raise RequestTimeoutError(path, err) from err
        except aiohttp.ClientError as err:
            logger.debug("Fallo de red o TLS al consultar %s", path, exc_info=err)
            raise TransportError(f"No se pudo conectar con TranvíaOnline ({path}).", err) from err

    async def _pace(self) -> None:
        """Separa las peticiones para no encadenarlas."""
        loop = asyncio.get_running_loop()
        if self._last_request_at is not None:
            wait = self._min_interval - (loop.time() - self._last_request_at)
            if wait > 0:
                await self._sleeper(wait)
        self._last_request_at = asyncio.get_running_loop().time()

    def _backoff_seconds(self, attempt: int, error: HttpStatusError | RequestTimeoutError) -> float:
        if isinstance(error, HttpStatusError) and error.retry_after is not None:
            return min(error.retry_after, 30.0)
        base = min(8.0, 0.8 * (2 ** (attempt - 1)))
        return base + random.uniform(0, 0.3)


def normalize_stop_code(value: str) -> str:
    """Código de tres o cuatro caracteres, o error si no puede ser una parada."""
    code = value.strip().upper()
    if not _STOP_CODE.fullmatch(code):
        raise StopNotFoundError(value)
    return code


def parse_arrivals(payload: Any, *, now: datetime | None = None) -> list[Arrival]:
    """Convierte el JSON de un panel en llegadas.

    Los elementos ilegibles se omiten. Si había elementos y ninguno vale, es
    un cambio de formato, no una parada vacía.
    """
    items = _as_dicts(payload)
    if not items:
        return []
    moment = now or datetime.now(UTC)
    arrivals: list[Arrival] = []
    for item in items:
        arrival = _parse_arrival(item, moment)
        if arrival is not None:
            arrivals.append(arrival)
    if not arrivals:
        raise ParseError()
    return arrivals


def parse_vehicles(payload: Any) -> list[Vehicle]:
    items = _as_dicts(payload)
    if not items:
        return []
    vehicles = [vehicle for item in items if (vehicle := _parse_vehicle(item)) is not None]
    if not vehicles:
        raise ParseError()
    return vehicles


@dataclass(frozen=True, slots=True)
class OccupancyIndex:
    """Ocupación separada por frescura. La vieja no se usa como estado actual."""

    fresh: dict[str, Occupancy]
    stale: tuple[Occupancy, ...]


def classify_occupancy(payload: Any, *, now: datetime, max_age: timedelta) -> OccupancyIndex:
    """Separa filas recientes de filas viejas, ambas indexables por servicio.

    TranvíaOnline deja filas de servicios que ya no circulan. Esas filas no se
    asocian a una unidad. Si un servicio se repite, se queda la fecha más nueva.
    """
    fresh: dict[str, Occupancy] = {}
    stale_by_service: dict[str, Occupancy] = {}
    for item in _as_dicts(payload):
        parsed = _parse_occupancy_item(item)
        if parsed is None:
            continue
        if _is_stale(parsed.updated_at, now, max_age):
            current = stale_by_service.get(parsed.service)
            if current is None or parsed.updated_at >= current.updated_at:
                stale_by_service[parsed.service] = parsed
            continue
        current = fresh.get(parsed.service)
        if current is None or parsed.updated_at >= current.updated_at:
            fresh[parsed.service] = parsed
    return OccupancyIndex(fresh=fresh, stale=tuple(stale_by_service.values()))


def parse_occupancy(
    payload: Any, *, now: datetime, max_age: timedelta
) -> tuple[dict[str, Occupancy], set[str]]:
    """Ocupación reciente por servicio y servicios cuya fila se ha descartado."""
    index = classify_occupancy(payload, now=now, max_age=max_age)
    return index.fresh, {item.service for item in index.stale}


def attach_occupancy(arrival: Arrival, fresh: dict[str, Occupancy], stale: set[str]) -> Arrival:
    """Une ocupación y número de vehículo por servicio.

    El número pintado sale de una fila reciente. Si la fila es vieja o no
    existe, no se inventa: solo se conserva un número que ya trajera esta
    misma fila del panel.
    """
    reported = arrival.vehicle_id
    occupancy = fresh.get(arrival.service)
    if occupancy is None:
        return replace(
            arrival,
            occupancy_percent=None,
            occupancy_raw=None,
            occupancy_fresh=False,
            occupancy_high=False,
            occupancy_updated_at=None,
            vehicle_id=reported,
            occupancy_discarded=arrival.service in stale,
        )
    return replace(
        arrival,
        occupancy_raw=occupancy.raw,
        occupancy_percent=normalize_carga(occupancy.raw),
        occupancy_high=occupancy.raw >= HIGH_CARGA,
        occupancy_fresh=True,
        occupancy_updated_at=occupancy.updated_at,
        vehicle_id=occupancy.vehicle_id if occupancy.vehicle_id is not None else reported,
        occupancy_discarded=False,
    )


def merge_occupancy(vehicle: Vehicle, fresh: dict[str, Occupancy], stale: set[str]) -> Vehicle:
    """Añade la ocupación reciente. El número de la fila vieja no se usa.

    Si vehicleLocation trae su propio número, ese sí se conserva: es de la
    posición que se acaba de leer, no de una fila antigua.
    """
    reported = vehicle.location_vehicle_id
    occupancy = fresh.get(vehicle.service)
    if occupancy is None:
        return replace(
            vehicle,
            occupancy_percent=None,
            occupancy_raw=None,
            occupancy_high=False,
            vehicle_id=reported,
            occupancy_updated_at=None,
            occupancy_discarded=vehicle.service in stale,
        )
    return replace(
        vehicle,
        occupancy_raw=occupancy.raw,
        occupancy_percent=normalize_carga(occupancy.raw),
        occupancy_high=occupancy.raw >= HIGH_CARGA,
        vehicle_id=occupancy.vehicle_id if occupancy.vehicle_id is not None else reported,
        occupancy_updated_at=occupancy.updated_at,
        occupancy_discarded=False,
    )


def filter_arrivals(
    arrivals: list[Arrival] | tuple[Arrival, ...],
    *,
    line: int | None = None,
    lines: tuple[int, ...] | list[int] | None = None,
    direction: int | None = None,
    destination: str | None = None,
) -> list[Arrival]:
    """Filtra y ordena llegadas por línea, sentido o destino."""
    allowed = set(lines or ())
    if line is not None:
        allowed.add(line)
    folded_destination = fold_destination(destination)
    selected: list[Arrival] = []
    for arrival in arrivals:
        if allowed and arrival.line not in allowed:
            continue
        if direction is not None and arrival.direction != direction:
            continue
        if folded_destination and not _destination_matches(arrival, folded_destination):
            continue
        selected.append(arrival)
    return _sort_arrivals(selected)


def fold_destination(destination: str | None) -> str:
    from metrotenerife.text import fold

    return fold(destination or "")


def _destination_matches(arrival: Arrival, folded_destination: str) -> bool:
    from metrotenerife.text import fold

    code = fold(arrival.destination_code)
    name = fold(arrival.destination_name)
    return folded_destination == code or folded_destination in name


def _sort_arrivals(arrivals: list[Arrival]) -> list[Arrival]:
    return sorted(
        arrivals, key=lambda arrival: (arrival.minutes, arrival.line, arrival.destination_name)
    )


def _as_dicts(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        dicts = [item for item in payload if isinstance(item, dict)]
        if payload and not dicts:
            raise ParseError()
        return dicts
    if isinstance(payload, dict):
        if (
            "stop" in payload
            or "service" in payload
            or "SERVICIO" in payload
            or "coordinate" in payload
        ):
            return [payload]
        collected: list[dict[str, Any]] = []
        for value in payload.values():
            if isinstance(value, list):
                collected.extend(item for item in value if isinstance(item, dict))
            elif isinstance(value, dict) and (
                "stop" in value
                or "service" in value
                or "SERVICIO" in value
                or "coordinate" in value
            ):
                collected.append(value)
        if collected:
            return collected
    raise ParseError()


def _parse_arrival(item: dict[str, Any], now: datetime) -> Arrival | None:
    try:
        minutes = int(item["remainingMinutes"])
        line = int(item["route"])
        direction = int(item["direction"])
    except (KeyError, TypeError, ValueError):
        return None
    if minutes < 0 or line <= 0 or direction <= 0:
        return None
    stop_code = str(item.get("stop") or "").strip().upper()
    destination_code = str(item.get("destinationStop") or "").strip().upper()
    service = str(item.get("service") or "").strip()
    if not stop_code or not destination_code or not service:
        return None
    updated_at, approximate = _timestamp(item, now)
    order = item.get("orderStop")
    return Arrival(
        service=service,
        stop_code=stop_code,
        stop_name=_title(item.get("stopDescription"), stop_code),
        destination_code=destination_code,
        destination_name=_title(item.get("destinationStopDescription"), destination_code),
        line=line,
        direction=direction,
        minutes=minutes,
        updated_at=updated_at,
        order=int(order) if isinstance(order, int | float | str) and str(order).isdigit() else None,
        approximate=approximate,
        vehicle_id=_optional_vehicle_id(item),
    )


def _parse_vehicle(item: dict[str, Any]) -> Vehicle | None:
    coordinate = item.get("coordinate")
    if not isinstance(coordinate, dict):
        return None
    try:
        lat = float(coordinate["lat"])
        lon = float(coordinate["lon"])
        line = int(item["route"])
        direction = int(item["direction"])
        minutes = int(item.get("remainingMinutes") or 0)
    except (KeyError, TypeError, ValueError):
        return None
    service = str(item.get("service") or "").strip()
    next_stop = str(item.get("nextStop") or "").strip().upper()
    destination = str(item.get("destinationStop") or "").strip().upper()
    if not service or not next_stop or not destination:
        return None
    order = item.get("orderStop")
    reported = _optional_vehicle_id(item)
    return Vehicle(
        service=service,
        lat=lat,
        lon=lon,
        line=line,
        direction=direction,
        minutes_to_next=minutes,
        next_stop_code=next_stop,
        next_stop_name=_title(item.get("nextStopDescription"), next_stop),
        destination_code=destination,
        destination_name=_title(item.get("destinationStopDescription"), destination),
        order=int(order) if isinstance(order, int | float | str) and str(order).isdigit() else None,
        vehicle_id=reported,
        location_vehicle_id=reported,
    )


def _parse_occupancy_item(item: dict[str, Any]) -> Occupancy | None:
    service = str(item.get("SERVICIO") if item.get("SERVICIO") is not None else "").strip()
    if not service:
        return None
    try:
        raw = int(item["CARGA"])
        updated_at = _parse_local(str(item["FECHA"]))
    except (KeyError, TypeError, ValueError):
        return None
    return Occupancy(
        service=service,
        raw=raw,
        updated_at=updated_at,
        vehicle_id=_optional_vehicle_id(item),
    )


def _is_stale(updated_at: datetime, now: datetime, max_age: timedelta) -> bool:
    return now - updated_at > max_age or updated_at - now > timedelta(minutes=5)


def _optional_vehicle_id(item: dict[str, Any]) -> int | None:
    """Número pintado, si esta fila lo trae. No se deduce del servicio."""
    for key in _VEHICLE_ID_KEYS:
        if key not in item or item[key] is None:
            continue
        raw = item[key]
        if isinstance(raw, bool):
            return None
        if isinstance(raw, int | float) and float(raw).is_integer() and int(raw) > 0:
            return int(raw)
        if isinstance(raw, str) and raw.strip().isdigit() and int(raw.strip()) > 0:
            return int(raw.strip())
        return None
    return None


def _timestamp(item: dict[str, Any], now: datetime) -> tuple[datetime, bool]:
    raw = item.get("lastUpdate")
    if isinstance(raw, int | float) and raw > 0:
        return datetime.fromtimestamp(raw / 1000, tz=UTC), False
    formatted = item.get("lastUpdateFormatted")
    if isinstance(formatted, str) and formatted.strip():
        try:
            return _parse_local(formatted), False
        except ValueError:
            pass
    return now, True


def _parse_local(value: str) -> datetime:
    naive = datetime.strptime(value.strip(), _LOCAL_TIME)
    return naive.replace(tzinfo=CANARY)


def _title(value: Any, fallback: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return fallback
    return " ".join(part.capitalize() for part in value.split())


def _retry_after(headers: Any) -> float | None:
    raw = headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        moment = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0.0, (moment - datetime.now(UTC)).total_seconds())
