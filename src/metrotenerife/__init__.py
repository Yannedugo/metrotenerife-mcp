"""Tiempos en vivo del Tranvía de Tenerife y punto de extensión para otros operadores."""

from metrotenerife.catalog import Catalog, load_catalog
from metrotenerife.client import TranviaOnlineClient, filter_arrivals
from metrotenerife.errors import (
    AmbiguousStopError,
    HttpStatusError,
    MetrotenerifeError,
    OperatorNotFoundError,
    ParseError,
    RequestTimeoutError,
    StopNotFoundError,
    TransportError,
)
from metrotenerife.models import Arrival, Line, Stop, Vehicle, VehicleSnapshot
from metrotenerife.operators import (
    AVISO_CATALOGO,
    AVISO_EN_VIVO,
    OperatorRegistry,
    TransitOperator,
    TranviaOperator,
)

__version__ = "0.1.0"

__all__ = [
    "AVISO_CATALOGO",
    "AVISO_EN_VIVO",
    "AmbiguousStopError",
    "Arrival",
    "Catalog",
    "HttpStatusError",
    "Line",
    "MetrotenerifeError",
    "OperatorNotFoundError",
    "OperatorRegistry",
    "ParseError",
    "RequestTimeoutError",
    "Stop",
    "StopNotFoundError",
    "TranviaOnlineClient",
    "TranviaOperator",
    "TransitOperator",
    "TransportError",
    "Vehicle",
    "VehicleSnapshot",
    "__version__",
    "filter_arrivals",
    "load_catalog",
]
