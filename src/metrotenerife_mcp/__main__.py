"""Arranque del servidor MCP: stdio en local, HTTP streamable para alojarlo."""

from __future__ import annotations

import argparse

from metrotenerife_mcp.server import build_server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="metrotenerife-mcp",
        description="Servidor MCP con los tiempos en vivo del Tranvía de Tenerife.",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="stdio para Claude Desktop o Cursor; http para alojarlo (streamable HTTP).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Dirección del transporte HTTP.")
    parser.add_argument("--port", type=int, default=8080, help="Puerto del transporte HTTP.")
    parser.add_argument("--path", default="/mcp", help="Ruta del transporte HTTP streamable.")
    args = parser.parse_args(argv)
    server = build_server()
    if args.transport == "stdio":
        server.run(transport="stdio")
        return
    server.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        streamable_http_path=args.path,
        json_response=True,
        stateless_http=True,
    )


if __name__ == "__main__":
    main()
