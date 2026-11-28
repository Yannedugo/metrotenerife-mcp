"""Tiempos en vivo del Tranvía de Tenerife y punto de extensión para otros operadores."""

from ._version import __version__
from .catalog import Catalog, load_catalog
from .client import TranviaOnlineClient, filter_arrivals
from .errors import (
    AmbiguousStopError,
    HttpStatusError,
    MetrotenerifeError,
    OperatorNotFoundError,
    ParseError,
    RequestTimeoutError,
    StopNotFoundError,
    TransportError,
)
from .models import Arrival, Line, Stop, Vehicle, VehicleSnapshot
from .operators import (
    AVISO_CATALOGO,
    AVISO_EN_VIVO,
    OperatorRegistry,
    TransitOperator,
    TranviaOperator,
)

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
