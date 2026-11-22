"""Arranca la página en http://127.0.0.1:8000."""

from __future__ import annotations

import argparse
import logging

from aiohttp import web

from metrotenerife_demo.app import create_app

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="metrotenerife-demo",
        description="Página local para contrastar los tiempos del tranvía con TranvíaOnline.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Dirección. Déjala en 127.0.0.1.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Puerto. Por defecto 8000.")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Escribe en el terminal la causa de los fallos de red o de certificado.",
    )
    args = parser.parse_args(argv)
    configure_logging(args.debug)
    url = f"http://{args.host}:{args.port}"
    print(f"Abre {url} en el navegador. Para parar, pulsa Ctrl+C.")
    web.run_app(create_app(), host=args.host, port=args.port)


def configure_logging(debug: bool) -> None:
    """INFO de normal, DEBUG con el traceback si se pide --debug."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s", force=True)
    logging.getLogger("metrotenerife").setLevel(level)
    logging.getLogger("metrotenerife_demo").setLevel(level)


if __name__ == "__main__":
    main()
