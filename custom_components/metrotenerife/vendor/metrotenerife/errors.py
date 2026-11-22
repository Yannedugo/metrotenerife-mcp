"""Errores de la librería.

Los mensajes están en español porque llegan a personas y a agentes.
"""

from __future__ import annotations


def describe_exception(exc: BaseException) -> str:
    """Tipo y mensaje breve, siguiendo la cadena de causas.

    En un Mac con el Python de python.org, el fallo real suele ser
    `CERTIFICATE_VERIFY_FAILED` dentro de otra excepción de aiohttp. El
    mensaje genérico no basta para verlo.
    """
    parts: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(parts) < 3:
        seen.add(id(current))
        text = " ".join(str(current).split())
        if len(text) > 160:
            text = text[:157] + "..."
        label = f"{type(current).__name__}: {text}" if text else type(current).__name__
        if label not in parts:
            parts.append(label)
        current = current.__cause__ or current.__context__
    return " | ".join(parts)


class MetrotenerifeError(Exception):
    """Error base de la librería."""


class StopNotFoundError(MetrotenerifeError):
    """Ninguna parada coincide con la consulta."""

    def __init__(self, query: str) -> None:
        self.query = query
        super().__init__(f"No hay ninguna parada que coincida con «{query}».")


class AmbiguousStopError(MetrotenerifeError):
    """La consulta encaja con varias paradas."""

    def __init__(self, query: str, matches: list[object]) -> None:
        self.query = query
        self.matches = matches
        names = ", ".join(getattr(stop, "code", str(stop)) for stop in matches)
        super().__init__(f"«{query}» coincide con varias paradas: {names}.")


class OperatorNotFoundError(MetrotenerifeError):
    """El identificador no corresponde a un operador registrado."""

    def __init__(self, operator_id: str, available: list[str]) -> None:
        self.operator_id = operator_id
        self.available = available
        listed = ", ".join(available) if available else "ninguno"
        super().__init__(
            f"El operador «{operator_id}» no está disponible. Operadores registrados: {listed}."
        )


class TransportError(MetrotenerifeError):
    """Fallo de red al hablar con la fuente en vivo."""

    def __init__(self, message: str, cause: BaseException | None = None) -> None:
        self.cause_type = type(cause).__name__ if cause else None
        detail = describe_exception(cause) if cause else ""
        super().__init__(f"{message} {detail}".strip())


class RequestTimeoutError(TransportError):
    """La fuente en vivo no respondió dentro del tiempo límite."""

    def __init__(self, path: str, cause: BaseException | None = None) -> None:
        self.path = path
        super().__init__(f"TranvíaOnline no respondió a tiempo ({path}).", cause)


class HttpStatusError(TransportError):
    """La fuente en vivo respondió con un estado HTTP de error."""

    def __init__(self, status: int, path: str, retry_after: float | None = None) -> None:
        self.status = status
        self.path = path
        self.retry_after = retry_after
        super().__init__(f"TranvíaOnline respondió HTTP {status} al consultar {path}.")

    @property
    def retryable(self) -> bool:
        """429 y los 5xx merecen un reintento; el resto, no."""
        return self.status == 429 or 500 <= self.status <= 599


class ParseError(MetrotenerifeError):
    """La respuesta no tiene la forma esperada."""

    def __init__(
        self, message: str = "La respuesta de TranvíaOnline no tiene el formato esperado."
    ) -> None:
        super().__init__(message)
