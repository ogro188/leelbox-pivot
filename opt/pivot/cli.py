#!/usr/bin/env python3
"""CLI para arrancar RADAR."""
import asyncio
import sys

import uvicorn

from kernel.api.app import create_app


def _run() -> None:
    """Arranca uvicorn con cierre ordenado.

    En Windows el ProactorEventLoop (el loop por defecto) lanza
    `OSError: [WinError 64] El nombre de red especificado ya no está disponible`
    al cerrar sockets con operaciones de aceptación pendientes. Usar el
    SelectorEventLoop evita ese error y mantiene HTTP/WebSocket sin problemas.
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    config = uvicorn.Config(app, host="0.0.0.0", port=8000, loop="asyncio")
    server = uvicorn.Server(config)

    try:
        asyncio.run(server.serve())
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True


if __name__ == "__main__":
    app = create_app()
    _run()
