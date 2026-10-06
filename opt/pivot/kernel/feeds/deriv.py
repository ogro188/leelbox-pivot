"""
Feed en tiempo real desde Deriv API (WebSocket - API 2026)
Soporta autenticación (OTP), historial de velas, suscripción OHLC y reconexión automática.
"""
import urllib.request
import asyncio
import json
import logging
import os
import time
from typing import Optional, Callable, Dict, Any, List
import websockets

logger = logging.getLogger(__name__)


class DerivConfig:
    """Configuración para conexión Deriv (nueva API api.derivws.com)"""
    def __init__(
        self,
        app_id: Optional[str] = None,
        symbol: str = "1HZ100V",
        timeframes: List[str] = None,
        api_token: Optional[str] = None,
        account_id: Optional[str] = None,
        account_type: str = "demo"
    ):
        self.app_id = app_id
        self.symbol = symbol
        self.timeframes = timeframes or ["M15", "H1"]
        self.api_token = api_token
        self.account_id = account_id
        self.account_type = account_type


class DerivFeed:
    """
    Feed en tiempo real desde Deriv API (nueva API).

    Características:
    - WebSocket público sin autenticación o autenticado vía OTP (PAT token)
    - Historial de velas vía WebSocket (ticks_history)
    - Suscripción a velas oficiales OHLC en tiempo real
    - Reconexión automática con backoff exponencial
    - Callbacks asíncronos para ticks, velas OHLC, historial y errores
    """

    REST_BASE = "https://api.derivws.com"
    PUBLIC_WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"

    def __init__(self, config: DerivConfig):
        self.config = config
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.running = False
        self.callbacks: Dict[str, List[Callable]] = {
            'tick': [],
            'ohlc': [],
            'history': [],
            'authorize': [],
            'error': [],
            'reconnect': []
        }
        self._task: Optional[asyncio.Task] = None
        self._reconnect_delay = 5
        self._max_reconnect_delay = 60
        self._pending_history: Dict[int, asyncio.Future] = {}
        self._request_id = 0
        self._auth_failures = 0
        # --- control de stream vivo (2026-10-04) ---
        self._last_tick: Dict[str, float] = {}
        self._resubscribe_fails = 0
        self._watch_task: Optional[asyncio.Task] = None
        # Segundos de silencio que se consideran "stream muerto". El WebSocket
        # puede quedar abierto (connected=True) mientras la suscripcion ya no
        # entrega ticks: es lo que pasaba al reabrir el mercado, porque la
        # suscripcion hecha con MarketIsClosed quedaba muerta.
        self._tick_stale_after = int(os.getenv("DERIV_TICK_STALE_SEC", "300"))

    def add_callback(self, event: str, callback: Callable):
        """Registrar callback para evento"""
        if event in self.callbacks:
            self.callbacks[event].append(callback)
        else:
            raise ValueError(f"Evento desconocido: {event}")

    def _trigger_callback(self, event: str, *args, **kwargs):
        """Ejecutar callbacks registrados"""
        for callback in self.callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(*args, **kwargs))
                else:
                    callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error en callback {event}: {e}")

    def _request_headers(self) -> Dict[str, str]:
        headers = {
            "Deriv-App-ID": self.config.app_id or "",
            "Content-Type": "application/json"
        }
        if self.config.api_token:
            headers["Authorization"] = f"Bearer {self.config.api_token}"
        return headers

    def _resolve_account_id(self) -> str:
        """Obtener el account_id (demo/real) desde la API REST"""
        req = urllib.request.Request(f"{self.REST_BASE}/trading/v1/options/accounts", headers=self._request_headers())
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
        accounts = data.get("data", [])
        for acc in accounts:
            if acc.get("account_type") == self.config.account_type and acc.get("status") == "active":
                return acc["account_id"]
        if accounts:
            return accounts[0]["account_id"]
        raise RuntimeError("No hay cuentas Deriv disponibles")

    def _get_otp_url(self) -> str:
        """Obtener URL WebSocket autenticada vía endpoint OTP"""
        account_id = self.config.account_id or self._resolve_account_id()
        url = f"{self.REST_BASE}/trading/v1/options/accounts/{account_id}/otp"
        req = urllib.request.Request(url, data=b"{}", method="POST", headers=self._request_headers())
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
        ws_url = data["data"]["url"]
        logger.info(f"OTP obtenido para cuenta {account_id}")
        return ws_url

    async def connect(self) -> bool:
        """Establecer conexión WebSocket (pública o autenticada via OTP)"""
        try:
            if self.config.api_token:
                ws_url = await asyncio.to_thread(self._get_otp_url)
                self.ws = await websockets.connect(ws_url, ping_interval=30, ping_timeout=10)
                self._reconnect_delay = 5
                logger.info("Conectado a Deriv API (autenticado)")
                await self._authorize()
            else:
                self.ws = await websockets.connect(self.PUBLIC_WS_URL, ping_interval=30, ping_timeout=10)
                self._reconnect_delay = 5
                logger.info("Conectado a Deriv API (modo público)")

            # Suscribirse a ticks por defecto
            await self._subscribe_ticks(self.config.symbol)

            # Suscribirse a OHLC para cada timeframe configurado
            for tf in self.config.timeframes:
                await self.subscribe_ohlc(self.config.symbol, self.get_granularity(tf))

            return True
        except Exception as e:
            logger.error(f"Error conectando a Deriv: {e}")
            return False

    async def _authorize(self):
        """Solicitar autorización de la sesión OTP actual"""
        req_id = self._next_request_id()
        await self.ws.send(json.dumps({
            "authorize": 1,
            "req_id": req_id
        }))
        logger.info("Enviada solicitud de autorización")

    async def _subscribe_ticks(self, symbol: str):
        """Suscribirse a ticks de un símbolo"""
        await self.ws.send(json.dumps({
            "ticks": symbol,
            "subscribe": 1
        }))
        logger.info(f"Suscrito a ticks de {symbol}")

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def fetch_candles_history(
        self,
        symbol: str,
        granularity: int,
        count: int
    ) -> List[Dict[str, Any]]:
        """
        Obtener historial de velas via WebSocket (ticks_history)
        
        Args:
            symbol: Símbolo (ej. 1HZ100V)
            granularity: Granularidad en segundos (60, 300, 900, 3600, 14400, 86400)
            count: Número de velas a obtener
        
        Returns:
            Lista de velas con campos: open, high, low, close, epoch
        """
        if not self.ws:
            raise RuntimeError("No hay conexión WebSocket activa")

        req_id = self._next_request_id()
        future = asyncio.get_event_loop().create_future()
        self._pending_history[req_id] = future

        await self.ws.send(json.dumps({
            "ticks_history": symbol,
            "granularity": granularity,
            "count": count,
            "style": "candles",
            "end": "latest",
            "req_id": req_id
        }))
        logger.info(f"Solicitado historial: {symbol} granularity={granularity} count={count}")

        try:
            result = await asyncio.wait_for(future, timeout=30)
            return result
        except asyncio.TimeoutError:
            self._pending_history.pop(req_id, None)
            raise TimeoutError(f"Timeout obteniendo historial para {symbol}")

    async def subscribe_ohlc(self, symbol: str, granularity: int):
        """
        Suscribirse a velas oficiales OHLC en tiempo real
        
        Args:
            symbol: Símbolo (ej. 1HZ100V)
            granularity: Granularidad en segundos (900 = M15, 3600 = H1, etc.)
        """
        if not self.ws:
            raise RuntimeError("No hay conexión WebSocket activa")

        await self.ws.send(json.dumps({
            "ticks_history": symbol,
            "granularity": granularity,
            "style": "candles",
            "end": "latest",
            "subscribe": 1
        }))
        logger.info(f"Suscrito a OHLC {symbol} granularity={granularity}")

    async def run(self):
        """Bucle principal de recepción de datos"""
        self.running = True

        while self.running:
            try:
                if not self.ws:
                    if not await self.connect():
                        await self._wait_reconnect()
                        continue

                message = await asyncio.wait_for(self.ws.recv(), timeout=30)
                await self._handle_message(json.loads(message))

            except asyncio.TimeoutError:
                try:
                    await self.ws.ping()
                except Exception as e:
                    logger.warning(f"Ping falló, reconectando: {e}")
                    self.ws = None
            except websockets.ConnectionClosed:
                logger.warning("Conexión cerrada, reconectando...")
                self.ws = None
                self._trigger_callback('reconnect')
                await self._wait_reconnect()
            except Exception as e:
                logger.error(f"Error procesando mensaje: {e}")
                self.ws = None
                await self._wait_reconnect()

    async def _vigilar_ticks(self):
        """Vigila que el stream de ticks siga vivo.

        Si pasan DERIV_TICK_STALE_SEC segundos sin ningun tick con el socket
        abierto, re-suscribe (barato, no tumba el servicio). Tras dos intentos
        fallidos, fuerza la reconexion del WebSocket.
        """
        while self.running:
            try:
                await asyncio.sleep(60)
                if not self.running or not self.ws:
                    continue
                simbolo = self.config.symbol
                ultimo = self._last_tick.get(simbolo)
                # Nunca llego un tick (mercado cerrado legitimo al arrancar):
                # no forzar nada.
                if ultimo is None:
                    continue
                silencio = time.time() - ultimo
                if silencio < self._tick_stale_after:
                    continue
                self._resubscribe_fails += 1
                if self._resubscribe_fails <= 2:
                    logger.warning(
                        f"Sin ticks de {simbolo} hace {int(silencio)}s "
                        f"-> re-suscribiendo (intento {self._resubscribe_fails})"
                    )
                    try:
                        await self._subscribe_ticks(simbolo)
                        if self.config.timeframes:
                            await self.subscribe_ohlc(
                                simbolo, self.get_granularity(self.config.timeframes[0])
                            )
                        await asyncio.sleep(20)
                    except Exception as e:
                        logger.error(f"Fallo al re-suscribir {simbolo}: {e}")
                else:
                    logger.error(
                        "Sin ticks pese a re-suscripciones: reconectando WebSocket"
                    )
                    self._resubscribe_fails = 0
                    self._trigger_callback('reconnect')
                    try:
                        await self.ws.close()
                    except Exception:
                        pass
                    self.ws = None
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error en vigilancia de ticks: {e}")

    async def _handle_message(self, data: Dict[str, Any]):
        """Router de mensajes según tipo"""
        msg_type = data.get("msg_type")

        if msg_type == "tick":
            await self._on_tick(data)
        elif msg_type == "ohlc":
            await self._on_ohlc(data)
        elif msg_type in ("candles", "history"):
            await self._on_history(data)
        elif msg_type == "authorize":
            await self._on_authorize(data)
        elif msg_type == "error":
            await self._on_error(data)
        elif msg_type == "subscription":
            logger.info(f"Suscripción confirmada: {data}")
        else:
            logger.warning(f"Mensaje desconocido: {data}")

    async def _on_tick(self, data: Dict[str, Any]):
        """Handler para ticks"""
        tick = data.get("tick", {})
        simbolo = tick.get("symbol") or self.config.symbol
        self._last_tick[simbolo] = time.time()
        self._resubscribe_fails = 0
        self._trigger_callback('tick', tick)

    async def _on_ohlc(self, data: Dict[str, Any]):
        """Handler para velas OHLC oficiales"""
        ohlc = data.get("ohlc", {})
        candle = {
            "symbol": ohlc.get("symbol"),
            "granularity": ohlc.get("granularity"),
            "open_time": ohlc.get("open_time"),
            "open": float(ohlc.get("open", ohlc.get("open_price", 0))),
            "high": float(ohlc.get("high", ohlc.get("high_price", 0))),
            "low": float(ohlc.get("low", ohlc.get("low_price", 0))),
            "close": float(ohlc.get("close", ohlc.get("close_price", 0))),
        }
        self._trigger_callback('ohlc', candle)

    async def _on_history(self, data: Dict[str, Any]):
        """Handler para respuesta de historial (msg_type 'candles' en la API nueva)"""
        req_id = data.get("req_id")
        future = self._pending_history.pop(req_id, None)
        if future and not future.done():
            candles = []
            for c in data.get("candles", []):
                candles.append({
                    "epoch": c.get("epoch"),
                    "open": float(c.get("open", 0)),
                    "high": float(c.get("high", 0)),
                    "low": float(c.get("low", 0)),
                    "close": float(c.get("close", 0)),
                    "volume": int(c.get("volume", 0))
                })
            future.set_result(candles)
            logger.info(f"Recibido historial: {len(candles)} velas")

    async def _on_authorize(self, data: Dict[str, Any]):
        """Handler para respuesta de autorización"""
        error = data.get("error")
        if error:
            code = error.get("code", "Unknown")
            message = error.get("message", "Unknown")
            logger.error(f"Error de autorización: {message} (código {code})")
            self._trigger_callback('error', error)

            self._auth_failures += 1
            if self._auth_failures >= 3:
                logger.error("Token inválido o expirado. Deteniendo reintentos.")
                self.running = False

            if self.ws:
                await self.ws.close()
                self.ws = None
        else:
            self._auth_failures = 0
            authorize = data.get("authorize", {})
            loginid = authorize.get("loginid", "unknown")
            currency = authorize.get("currency", "unknown")
            balance = authorize.get("balance", "unknown")
            logger.info(f"Autenticado: {loginid} | {currency} {balance}")
            self._trigger_callback('authorize', authorize)

    async def _on_error(self, data: Dict[str, Any]):
        """Handler para errores"""
        error = data.get("error", {})
        msg = error.get("message", "Error desconocido")
        logger.error(f"Error Deriv: {msg}")
        self._trigger_callback('error', error)

    async def _wait_reconnect(self):
        """Esperar antes de reconectar con backoff exponencial"""
        delay = min(self._reconnect_delay, self._max_reconnect_delay)
        logger.info(f"Reconectando en {delay}s...")
        await asyncio.sleep(delay)
        self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)

    def stop(self):
        """Detener feed"""
        self.running = False
        if self._task:
            self._task.cancel()
        if self._watch_task:
            self._watch_task.cancel()
        if self.ws:
            asyncio.create_task(self.ws.close())

    def start(self):
        """Iniciar feed en background"""
        self._task = asyncio.create_task(self.run())
        self._watch_task = asyncio.create_task(self._vigilar_ticks())
        return self._task

    @staticmethod
    def get_granularity(tf: str) -> int:
        """Convertir timeframe a granularidad en segundos"""
        mapping = {
            'M1': 60, 'M5': 300, 'M15': 900, 'M30': 1800,
            'H1': 3600, 'H4': 14400, 'D1': 86400
        }
        return mapping.get(tf, 900)


def create_deriv_feed(
    symbol: str = "1HZ100V",
    timeframes: List[str] = None,
    api_token: Optional[str] = None,
    on_candle: Optional[Callable] = None
) -> DerivFeed:
    """Factory function para crear feed Deriv"""
    if timeframes is None:
        timeframes = ['M15', 'H1']

    config = DerivConfig(symbol=symbol, timeframes=timeframes, api_token=api_token)
    feed = DerivFeed(config)

    if on_candle:
        feed.add_callback('ohlc', on_candle)

    return feed