#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Punto de entrada para el servicio WebSocket de Deriv.
Se ejecuta como contenedor independiente (pivot-ws).
"""
import asyncio
import os
import signal
import sys
import logging
from typing import Optional

# Añadir el directorio raíz al path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kernel.feeds.deriv import DerivFeed, DerivConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("deriv-ws")


async def run_deriv_feed():
    """Crea y ejecuta el feed Deriv hasta señal de parada."""
    app_id = os.getenv("DERIV_APP_ID") or None
    symbol = os.getenv("DERIV_SYMBOL", "1HZ100V")
    timeframes = os.getenv("DERIV_TIMEFRAMES", "M15,H1").split(",")
    api_token = os.getenv("DERIV_API_TOKEN") or None
    account_type = os.getenv("DERIV_ACCOUNT_TYPE", "demo")
    account_id = os.getenv("DERIV_ACCOUNT_ID") or None

    if api_token:
        logger.info("Token Deriv detectado, autenticando...")
    else:
        logger.warning("DERIV_API_TOKEN no configurado, operando en modo público (sin autenticar)")

    config = DerivConfig(
        app_id=app_id,
        symbol=symbol,
        timeframes=timeframes,
        api_token=api_token,
        account_id=account_id,
        account_type=account_type
    )
    feed = DerivFeed(config)

    # Callbacks básicos para logging
    def on_candle(candle: dict):
        logger.debug(f"OHLC: {candle}")
    def on_tick(tick: dict):
        logger.debug(f"Tick: {tick}")
    def on_history(candles: list):
        logger.info(f"Historial recibido: {len(candles)} velas")
    def on_authorize(auth: dict):
        logger.info(f"Autorizado: {auth.get('loginid', auth.get('email', 'N/A'))}")

    def on_error(error: dict):
        logger.error(f"Error Deriv: {error}")

    def on_reconnect():
        logger.warning("Reconectando...")

    feed.add_callback("ohlc", on_candle)
    feed.add_callback("tick", on_tick)
    feed.add_callback("history", on_history)
    feed.add_callback("authorize", on_authorize)
    feed.add_callback("error", on_error)
    feed.add_callback("reconnect", on_reconnect)

    # Manejo de señales para shutdown limpio
    stop_event = asyncio.Event()

    def _signal_handler(signum, frame):
        logger.info(f"Señal {signum} recibida, cerrando...")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _signal_handler)
        except (OSError, ValueError):
            pass  # Windows o entorno sin señales

    logger.info(f"Iniciando DerivFeed: symbol={symbol}, timeframes={timeframes}")

    connected = await feed.connect()
    if not connected:
        logger.error("No se pudo conectar a Deriv API. Abortando.")
        sys.exit(1)

    # Bucle de recepción en background (processa ticks/ohlc/historial/auth)
    run_task = asyncio.create_task(feed.run())

    # Mantener vivo hasta stop
    await stop_event.wait()

    logger.info("Deteniendo DerivFeed...")
    feed.stop()
    run_task.cancel()
    try:
        await run_task
    except asyncio.CancelledError:
        pass
    logger.info("DerivFeed detenido correctamente")


if __name__ == "__main__":
    try:
        asyncio.run(run_deriv_feed())
    except KeyboardInterrupt:
        logger.info("Interrumpido por usuario")
    except Exception as e:
        logger.exception(f"Error fatal: {e}")
        sys.exit(1)