# -*- coding: utf-8 -*-
"""
Runtime Deriv en vivo para el API.
- Conecta a Deriv WS (público o con token del .env).
- Por cada activo con fuente deriv: suscribe ticks + OHLC M15.
- Mantiene un buffer de velas M15 reales (seed desde historial real de Deriv).
- Al cerrarse cada vela M15, alimenta el detector PIVOT real (PivotRadarEngine
  v8) con los DataFrames M15/H1/H4/D1 y difunde por WebSocket las señales que
  genera el detector (deduplicadas por id). El mensaje es el build_alert_text
  del detector, y el propio detector envía la alerta ntfy.
- Expone estado de conexión global y por activo.
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable

import pandas as pd

from kernel.feeds.deriv import DerivFeed, DerivConfig
from kernel.api.websocket_server import manager

logger = logging.getLogger(__name__)


def _normalizar_historial(candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normaliza velas del historial de Deriv al formato del buffer interno."""
    out = []
    for c in candles:
        try:
            out.append({
                "time": int(c.get("epoch", 0)),
                "open": float(c.get("open", 0)),
                "high": float(c.get("high", 0)),
                "low": float(c.get("low", 0)),
                "close": float(c.get("close", 0)),
                "volume": int(c.get("volume", 0)),
            })
        except (TypeError, ValueError):
            continue
    return out


class AssetDerivStream:
    """Stream de un activo: feed Deriv + buffer M15 + generación de señales."""

    def __init__(
        self,
        simbolo: str,
        instrumento: str,
        config: DerivConfig,
        activo_info: Any,
        serialize_senal: Callable,
        db: Any,
    ):
        self.simbolo = simbolo
        self.instrumento = instrumento
        self.config = config
        self.activo_info = activo_info
        self.serialize_senal = serialize_senal
        self.db = db

        self.feed: Optional[DerivFeed] = None
        self.running = False
        self.connected = False
        self.last_error: Optional[str] = None

        self.buffer: List[Dict[str, Any]] = []
        self._current: Optional[Dict[str, Any]] = None
        self._last_open_time: Optional[int] = None
        self._sent_signals: set = set()
        self._task: Optional[asyncio.Task] = None
        self._last_tick_ts: float = 0.0
        self.engine: Optional[Any] = None  # PivotRadarEngine (detector v8)
        self._df_h1: pd.DataFrame = pd.DataFrame()
        self._df_h4: pd.DataFrame = pd.DataFrame()
        self._df_d1: pd.DataFrame = pd.DataFrame()

    @property
    def price(self) -> Optional[float]:
        if self._current:
            return self._current["close"]
        if self.buffer:
            return self.buffer[-1]["close"]
        return None

    # ------------------------------------------------------------------ vida
    async def start(self) -> bool:
        """Crea el feed, conecta, siembra historial y arranca el loop de datos."""
        self.feed = DerivFeed(self.config)
        self.feed.add_callback("tick", self._on_tick)
        self.feed.add_callback("ohlc", self._on_ohlc)
        self.feed.add_callback("reconnect", self._on_reconnect)
        self.feed.add_callback("error", self._on_error)

        try:
            ok = await self.feed.connect()
        except Exception as e:
            self.last_error = str(e)
            self.connected = False
            logger.error(f"[{self.simbolo}] Error conectando a Deriv: {e}")
            return False

        if not ok:
            self.connected = False
            self.last_error = "No se pudo conectar a Deriv API"
            logger.error(f"[{self.simbolo}] No se pudo conectar a Deriv API")
            return False

        self.connected = True
        self.last_error = None

        # Arrancar el loop de recepción ANTES de pedir historial, así las
        # respuestas (ticks_history -> on_history) resuelven sus futures.
        self._task = asyncio.create_task(self.feed.run())

        # Sembrar buffer con historial real de M15
        try:
            hist = await self.feed.fetch_candles_history(self.instrumento, 900, 500)
            self.buffer = _normalizar_historial(hist)
            self.buffer.sort(key=lambda c: c["time"])
            logger.info(f"[{self.simbolo}] Historial sembrado: {len(self.buffer)} velas M15")
        except Exception as e:
            logger.warning(f"[{self.simbolo}] No se pudo sembrar historial: {e}")

        # Sembrar historial de H1/H4/D1 (contexto estructural del detector)
        await self._sembrar_dfs_superiores()

        # Construir el detector PIVOT v8 real y precargar su estado con el
        # historial sembrado: los detectores ya deduplican por barra, así que
        # solo se notificarán señales NUEVAS a partir del live stream.
        try:
            self.engine = await asyncio.to_thread(self._construir_motor)
            await asyncio.to_thread(self._precargar_motor)
        except Exception as e:
            logger.error(f"[{self.simbolo}] Error inicializando detector PIVOT: {e}")
            self.engine = None

        self.running = True
        logger.info(f"[{self.simbolo}] Stream Deriv iniciado ({self.instrumento})")
        return True

    async def stop(self):
        self.running = False
        if self.feed:
            try:
                self.feed.stop()
            except Exception as e:
                logger.warning(f"[{self.simbolo}] Error deteniendo feed: {e}")
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.connected = False
        logger.info(f"[{self.simbolo}] Stream Deriv detenido")

    # ------------------------------------------------------------- callbacks
    def _on_tick(self, tick: Dict[str, Any]):
        """Tick real: actualiza la vela formándose y difunde precio."""
        # Recibir un tick demuestra que el enlace vive. El flag solo se
        # marcaba False en _on_reconnect() y nunca volvia a True hasta
        # reiniciar el servicio: el panel mostraba PARADO con precio moviendose.
        if not self.connected:
            self.connected = True
            self.last_error = None
            logger.info(f"[{self.simbolo}] Stream Deriv recuperado (tick recibido)")
        try:
            quote = float(tick.get("quote", 0))
        except (TypeError, ValueError):
            return
        now = time.monotonic()
        # Throttle: no spamear el WS más de ~4 veces/seg
        if now - self._last_tick_ts < 0.25:
            return
        self._last_tick_ts = now

        if self._current:
            self._current["close"] = quote
            self._current["high"] = max(self._current["high"], quote)
            self._current["low"] = min(self._current["low"], quote)

        asyncio.ensure_future(manager.broadcast({
            "type": "tick",
            "asset": self.simbolo,
            "price": quote,
            "bid": quote,
            "ask": quote,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))

    def _on_ohlc(self, candle: Dict[str, Any]):
        """OHLC streaming: cierra la vela anterior cuando cambia open_time."""
        try:
            open_time = int(candle.get("open_time", 0))
            o = float(candle.get("open", 0))
            h = float(candle.get("high", 0))
            l = float(candle.get("low", 0))
            c = float(candle.get("close", 0))
        except (TypeError, ValueError):
            return

        # Nueva vela -> la anterior (si existía) queda cerrada
        if self._last_open_time is not None and open_time != self._last_open_time:
            if self._current:
                self.buffer.append(self._current)
                self.buffer = self.buffer[-2000:]
            asyncio.ensure_future(self._on_bar_cerrada())

        self._current = {
            "time": open_time,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": 0,
        }
        self._last_open_time = open_time

        # Difundir vela formándose para que el chart se mueva en vivo
        asyncio.ensure_future(manager.broadcast({
            "type": "candle",
            "asset": self.simbolo,
            "timeframe": "M15",
            "data": self._current,
        }))

    def _on_reconnect(self):
        self.connected = False
        logger.warning(f"[{self.simbolo}] Reconectando a Deriv...")

    def _on_error(self, error: Dict[str, Any]):
        self.last_error = str(error.get("message", "Error Deriv"))
        logger.error(f"[{self.simbolo}] Error Deriv: {self.last_error}")

    # ------------------------------------------------------ generación de señales
    async def _on_bar_cerrada(self):
        """Vela M15 cerrada: alimenta el detector PIVOT v8 y emite sus señales nuevas."""
        if self.engine is None or len(self.buffer) < 55:
            return
        try:
            dfs = self._dfs_para_motor()
            await asyncio.to_thread(self.engine.on_data, *dfs)
        except Exception as e:
            logger.error(f"[{self.simbolo}] Error en detector PIVOT live: {e}")
            return

        señales = self._nuevas_senales_motor()
        for payload in señales:
            try:
                await self._persistir(payload)
            except Exception as e:
                logger.error(f"[{self.simbolo}] Error persistiendo señal: {e}")
            await manager.broadcast({
                "type": "signal",
                "data": payload,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            await manager.send_console_log({
                "ts": datetime.now(timezone.utc).isoformat(),
                "t": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                "level": "INFO",
                "cat": "PIVOT",
                "msg": f"Señal {'LONG' if payload.get('direccion') == 1 else 'SHORT'} {payload.get('asset')} @ {payload.get('precio')}",
            })

    # ------------------------------------------------------ detector PIVOT v8
    async def _sembrar_dfs_superiores(self):
        """Sembra H1/H4/D1 reales desde Deriv para dar contexto al detector."""
        try:
            h1 = await self.feed.fetch_candles_history(self.instrumento, 3600, 600)
            h4 = await self.feed.fetch_candles_history(self.instrumento, 14400, 300)
            d1 = await self.feed.fetch_candles_history(self.instrumento, 86400, 220)
            self._df_h1 = self._df_desde_hist(h1)
            self._df_h4 = self._df_desde_hist(h4)
            self._df_d1 = self._df_desde_hist(d1)
            logger.info(
                f"[{self.simbolo}] Contexto sembrado: H1={len(self._df_h1)} "
                f"H4={len(self._df_h4)} D1={len(self._df_d1)}"
            )
        except Exception as e:
            logger.warning(f"[{self.simbolo}] No se pudo sembrar contexto superior: {e}")
            self._df_h1 = pd.DataFrame()
            self._df_h4 = pd.DataFrame()
            self._df_d1 = pd.DataFrame()

    @staticmethod
    def _df_desde_hist(candles: List[Dict[str, Any]]) -> pd.DataFrame:
        rows = _normalizar_historial(candles)
        rows.sort(key=lambda c: c["time"])
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
        df = df[["open", "high", "low", "close", "volume"]]
        return df

    def _df_m15(self) -> pd.DataFrame:
        rows = list(self.buffer)
        rows.sort(key=lambda c: c["time"])
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
        df = df[["open", "high", "low", "close", "volume"]]
        return df

    def _dfs_para_motor(self) -> tuple:
        """Combina contexto sembrado + buffer M15 live para alimentar el detector.

        Los timeframes superiores conservan la profundidad sembrada (H1/H4/D1)
        y se actualizan con las velas más recientes resampleando el buffer M15.
        """
        from kernel.feeds.csv_resample import resamplear_ohlc

        df_m15 = self._df_m15()
        df_h1 = self._combinar_superior(self._df_h1, df_m15, "H1")
        df_h4 = self._combinar_superior(self._df_h4, df_m15, "H4")
        df_d1 = self._combinar_superior(self._df_d1, df_m15, "D1")
        return (df_m15, df_h1, df_h4, df_d1)

    @staticmethod
    def _combinar_superior(base: pd.DataFrame, df_m15: pd.DataFrame, tf: str) -> pd.DataFrame:
        """Base sembrada + velas recientes del buffer (dedupe por timestamp)."""
        from kernel.feeds.csv_resample import resamplear_ohlc

        if df_m15 is None or df_m15.empty or len(df_m15) < 55:
            return base
        try:
            reciente = resamplear_ohlc(df_m15, tf)
        except Exception as e:
            logger.error(f"Error resampleando {tf} para contexto superior: {e}")
            return base
        if reciente is None or reciente.empty:
            return base
        if base is not None and not base.empty:
            combinado = pd.concat([base, reciente])
            combinado = combinado[~combinado.index.duplicated(keep="last")]
            return combinado.sort_index()
        return reciente

    def _construir_motor(self):
        """Crea el PivotRadarEngine (detector v8) con la config del activo."""
        from core.motor_v8 import PivotRadarEngine
        from kernel.ntfy import cargar_config_activo

        cfg = cargar_config_activo(self.simbolo) or {}
        point = getattr(self.activo_info, "punto", 0.00001) or 0.00001
        self.engine = PivotRadarEngine(
            symbol=self.simbolo,
            ntfy_topic=cfg.get("topic", ""),
            ntfy_server=cfg.get("server", "https://ntfy.sh"),
            modo_test=False,
            point=point,
            broker_tz_offset_hours=2,
            data_dir=f"pivotradar_data/{self.simbolo.lower()}",
        )
        return self.engine

    def _precargar_motor(self):
        """Alimenta al detector con el historial sembrado para poblar buffers,
        estructura y latches: las señales de estas velas NO se emiten ni se
        envían alertas."""
        if self.engine is None or len(self.buffer) < 55:
            return
        topic_backup = self.engine.alertas.ntfy_topic
        self.engine.alertas.ntfy_topic = ""  # silenciar durante la precarga
        try:
            dfs = self._dfs_para_motor()
            self.engine.on_data(*dfs)
            # Descarta cualquier alerta encolada durante la precarga: esas
            # señales del historial no deben notificarse.
            self.engine.alertas.g_alert_queue = []
        finally:
            self.engine.alertas.ntfy_topic = topic_backup
        for sig in self.engine.g_pending_signals:
            if sig.id:
                self._sent_signals.add(str(sig.id))
        logger.info(f"[{self.simbolo}] Detector precargado. Señales historial: {len(self._sent_signals)}")

    def _serializar_motor(self, sig) -> Optional[Dict[str, Any]]:
        """Convierte una Signal del detector v8 al DTO del frontend.

        La narrativa es el mensaje del detector (build_alert_text), el mismo
        texto que envía por ntfy.
        """
        try:
            ts = int(sig.entry_time.timestamp() * 1000) if sig.entry_time else int(datetime.now(timezone.utc).timestamp() * 1000)
            precio = float(sig.entry_price)
            objetivo = float(sig.hipotesis_objetivo) if sig.hipotesis_objetivo else None
            invalidez = float(sig.invalidez_estructural) if sig.invalidez_estructural else None
            narrativa = self.engine.alertas.build_alert_text(sig)
            return {
                "id": str(sig.id),
                "ts": ts,
                "asset": sig.symbol or self.simbolo,
                "estrategia": "PIVOT",
                "etiqueta": sig.tipo or f"{sig.detector}",
                "direccion": int(sig.direction),
                "precio": precio,
                "expiracion_velas": int(sig.hipotesis_expiry_velas or 0),
                "confianza": [int(sig.hipotesis_prob_min or 0), int(sig.hipotesis_prob_max or 0)],
                "objetivo": objetivo,
                "invalidacion": invalidez,
                "narrativa": narrativa,
                "estado": "activa",
                "detectores": [sig.detector],
                "fuente": "deriv",
                "datos_prueba": False,
            }
        except Exception as e:
            logger.error(f"[{self.simbolo}] Error serializando señal del detector: {e}")
            return None

    def _nuevas_senales_motor(self) -> List[Dict[str, Any]]:
        """Devuelve las señales nuevas del detector (las que aún no se emitieron)."""
        if self.engine is None:
            return []
        nuevas = []
        for sig in list(self.engine.g_pending_signals):
            if sig.id and str(sig.id) in self._sent_signals:
                continue
            payload = self._serializar_motor(sig)
            if payload:
                self._sent_signals.add(str(sig.id))
                nuevas.append(payload)
        return nuevas

    async def _persistir(self, sig: Dict[str, Any]):
        if not self.db:
            return
        entry_time = datetime.fromtimestamp(sig["ts"] / 1000, tz=timezone.utc)
        await self.db.guardar_senal_core(
            signal_id=str(sig["id"]),
            entry_time=entry_time,
            symbol=sig["asset"],
            direction=sig["direccion"],
            entry_price=sig["precio"],
            detector=",".join(sig.get("detectores", []) or ["D0"]),
            tipo=sig["etiqueta"],
            hipotesis_prob_min=sig["confianza"][0],
            hipotesis_prob_max=sig["confianza"][1],
            hipotesis_expiry_velas=sig["expiracion_velas"],
            conviccion=sig["confianza"][1] / 100.0,
            regimen_volatilidad="NORMAL",
            fuente="deriv",
        )

    def status(self) -> Dict[str, Any]:
        return {
            "simbolo": self.simbolo,
            "instrumento": self.instrumento,
            "connected": self.connected,
            "running": self.running,
            "price": self.price,
            "velas_buffer": len(self.buffer),
            "señales_enviadas": len(self._sent_signals),
            "last_error": self.last_error,
            "tick_reciente": bool(
                self._last_tick_ts
                and (time.monotonic() - self._last_tick_ts) < 60
            ),
        }


class DerivRuntime:
    """Gestor multi-activo de streams Deriv."""

    def __init__(self, activos_info: Dict[str, Any], serialize_senal: Callable, db: Any):
        self.activos_info = activos_info  # simbolo -> ActivoInfo
        self.serialize_senal = serialize_senal
        self.db = db
        self.streams: Dict[str, AssetDerivStream] = {}
        self.connected = False
        self._tasks: List[asyncio.Task] = []

    def _instrumento_para(self, simbolo: str) -> str:
        path = f"activos/{simbolo.lower()}.json"
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                fc = data.get("fuente_config") or {}
                if fc.get("instrumento"):
                    return fc["instrumento"]
            except Exception as e:
                logger.error(f"Error leyendo fuente_config de {path}, usando frx{simbolo}: {e}")
        return f"frx{simbolo}"

    def _config_para(self, simbolo: str) -> DerivConfig:
        return DerivConfig(
            app_id=os.getenv("DERIV_APP_ID") or None,
            symbol=self._instrumento_para(simbolo),
            timeframes=["M15"],
            api_token=os.getenv("DERIV_API_TOKEN") or None,
            account_type=os.getenv("DERIV_ACCOUNT_TYPE", "demo"),
            account_id=os.getenv("DERIV_ACCOUNT_ID") or None,
        )

    async def start(self):
        """Conecta un stream por activo de fuente deriv (secuencial para evitar
        colisiones en el flujo OTP)."""
        for simbolo in list(self.activos_info.keys()):
            stream = AssetDerivStream(
                simbolo=simbolo,
                instrumento=self._instrumento_para(simbolo),
                config=self._config_para(simbolo),
                activo_info=self.activos_info[simbolo],
                serialize_senal=self.serialize_senal,
                db=self.db,
            )
            self.streams[simbolo] = stream
            try:
                await stream.start()
            except Exception as e:
                logger.error(f"[{simbolo}] Error arrancando stream: {e}")
        self.connected = any(s.connected for s in self.streams.values())
        await self._broadcast_status()

    async def stop(self):
        for stream in self.streams.values():
            try:
                await stream.stop()
            except Exception:
                pass
        self.streams.clear()
        for t in self._tasks:
            t.cancel()
        self._tasks = []
        self.connected = False

    async def _broadcast_status(self):
        await manager.broadcast({
            "type": "status",
            "deriv_connected": self.connected,
            "assets": {s: self.streams[s].status() for s in self.streams},
        })

    async def notify_status(self):
        self.connected = any(s.connected for s in self.streams.values())
        await self._broadcast_status()

    def status(self) -> Dict[str, Any]:
        conectado = any(s.connected for s in self.streams.values())
        self.connected = conectado
        return {
            "connected": conectado,
            "assets": {s: self.streams[s].status() for s in self.streams},
        }
