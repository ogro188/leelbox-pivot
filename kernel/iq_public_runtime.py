# -*- coding: utf-8 -*-
"""
Runtime OTC de IQ Option para el API PIVOT.

Solo datos: no hay login, no hay órdenes ni ejecución. El único proceso que
habla con el GraphQL público es ``scripts/iq_public_collector.py``; este
runtime se limita a leer su SQLite en modo read-only.

Por cada activo ``fuente_tipo == "iqoption_public"``:
- Carga las velas M15 ya cerradas que dejó el collector.
- Precalienta ``PivotRadarEngine`` con ese histórico, silenciando alertas.
- Cada vez que el collector cierra una nueva M15, alimenta el motor con
  M15/H1/H4/D1 (los superiores se resamplean desde M15).
- Persiste las señales nuevas en ``senales_core`` con
  ``fuente='iqoption_public'``.
- Solo difunde por WebSocket si el activo tiene ``"visible": true`` en su JSON.
  El panel sigue mostrando únicamente los activos reales hasta validar el
  histórico OTC.

Los símbolos incluyen el sufijo ``-OTC`` para no mezclarse con los reales en
histórico, panel ni backtests. El OTC es sintético y estos datos son insumo de
investigación, no precios de mercado real.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from kernel.api.websocket_server import manager
from kernel.feeds.iq_public_backfill import fusionar_velas, quotes_to_m15

logger = logging.getLogger(__name__)

DEFAULT_DB = os.getenv("IQ_PUBLIC_DB", os.path.join("data", "iq_public", "iq_public.db"))
DEFAULT_POLL_SECONDS = float(os.getenv("IQ_PUBLIC_RUNTIME_POLL", "5"))
TF_SECONDS: Dict[str, int] = {"M1": 60, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
MIN_M15_PARA_MOTOR = 55
MAX_BUFFER = 2000
FUENTE = "iqoption_public"
# Una vela más vieja que esto se usa para calentar indicadores, pero no emite
# señales: evita persistir señales atrasadas tras una caída del collector.
MAX_EMIT_AGE = 2 * 900
# Hueco máximo tolerado dentro del buffer del motor. Un corte mayor reinicia
# el buffer para no encadenar velas que en realidad no son consecutivas.
MAX_GAP_SECONDS = int(os.getenv("IQ_PUBLIC_MAX_GAP_SECONDS", str(2 * 900)))

# Calentamiento con ``charts.d1``. Rellena huecos del buffer con velas
# sintéticas de ~8 min de resolución. Después de usarlo se silencian las
# primeras velas reales para que los detectores no reaccionen al empalme.
BACKFILL_ENABLED = os.getenv("IQ_PUBLIC_BACKFILL", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
BACKFILL_SUPPRESS_BARS = max(
    0, int(os.getenv("IQ_PUBLIC_BACKFILL_SUPPRESS_BARS", "4"))
)
# Si el collector dejó de refrescar charts, no se usan: preferimos el
# comportamiento conservador antes que calentar con datos viejos.
CHART_MAX_AGE = float(os.getenv("IQ_PUBLIC_CHART_MAX_AGE", "1800"))


def _iso_utc(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def _bar_a_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "time": int(row["open_time"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": int(row["ticks"] or 0),
    }


class IQPublicStore:
    """Lector read-only de la SQLite que escribe el collector OTC."""

    def __init__(self, db_path: str):
        self.path = Path(db_path).expanduser()

    def _connect(self) -> sqlite3.Connection:
        if not self.path.exists():
            raise FileNotFoundError(f"No existe la DB OTC: {self.path}")
        conn = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def bars(
        self,
        provider_name: str,
        timeframe: str = "M15",
        *,
        count: Optional[int] = None,
        closed_only: bool = False,
        since_open_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Velas de un proveedor, en orden cronológico.

        ``closed_only`` descarta la vela en curso usando el reloj local: una
        vela M15 solo se considera cerrada cuando ``open_time + 900 <= now``.
        """
        tf = str(timeframe).upper()
        if tf not in TF_SECONDS:
            raise ValueError(f"Timeframe no soportado: {timeframe}")
        where = ["provider_name = ?", "timeframe = ?"]
        params: List[Any] = [provider_name, tf]
        if closed_only:
            where.append("open_time <= ?")
            params.append(int(time.time()) - TF_SECONDS[tf])
        if since_open_time is not None:
            where.append("open_time > ?")
            params.append(int(since_open_time))

        sql = (
            "SELECT open_time, open, high, low, close, ticks, first_tick_ts, last_tick_ts "
            "FROM bars WHERE " + " AND ".join(where)
        )
        if count:
            sql += " ORDER BY open_time DESC LIMIT ?"
            params.append(int(count))
            sql = f"SELECT * FROM ({sql}) ORDER BY open_time ASC"
        else:
            sql += " ORDER BY open_time ASC"

        with closing(self._connect()) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_bar_a_dict(r) for r in rows]

    def latest_bar(self, provider_name: str, timeframe: str = "M15") -> Optional[Dict[str, Any]]:
        tf = str(timeframe).upper()
        if tf not in TF_SECONDS:
            raise ValueError(f"Timeframe no soportado: {timeframe}")
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT open_time, open, high, low, close, ticks, first_tick_ts, last_tick_ts
                FROM bars WHERE provider_name=? AND timeframe=?
                ORDER BY open_time DESC LIMIT 1
                """,
                (provider_name, tf),
            ).fetchone()
        return _bar_a_dict(row) if row else None

    def chart_quotes(
        self,
        provider_name: str,
        period: str = "d1",
    ) -> List[Dict[str, Any]]:
        """Puntos históricos de ``charts`` persistidos por el collector.

        Devuelve lista vacía si la DB es anterior a la tabla ``chart_quotes``.
        """
        with closing(self._connect()) as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT ts, price FROM chart_quotes
                    WHERE provider_name=? AND period=?
                    ORDER BY ts
                    """,
                    (provider_name, str(period).lower()),
                ).fetchall()
            except sqlite3.OperationalError:
                return []
        return [
            {"timestamp": int(row["ts"]), "price": float(row["price"])}
            for row in rows
            if row["price"] is not None
        ]

    def last_tick(self, provider_name: str) -> Optional[Dict[str, Any]]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT ts, price, bid, ask, latency_ms
                FROM ticks WHERE provider_name=?
                ORDER BY ts DESC LIMIT 1
                """,
                (provider_name,),
            ).fetchone()
        if not row:
            return None
        return {
            "ts": float(row["ts"]),
            "price": float(row["price"]),
            "bid": row["bid"],
            "ask": row["ask"],
            "latency_ms": row["latency_ms"],
        }

    def health(self) -> Optional[Dict[str, Any]]:
        """Último registro de salud del collector (None si no hay o falla)."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM collector_health ORDER BY ts DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["age_s"] = max(0.0, time.time() - float(data["ts"]))
        data["ts_iso"] = _iso_utc(data["ts"])
        return data


class AssetIQPublicStream:
    """Puente OTC para un activo: SQLite -> buffer M15 -> PivotRadarEngine."""

    def __init__(
        self,
        simbolo: str,
        provider_name: str,
        active_id: Optional[int],
        visible: bool,
        punto: float,
        store: IQPublicStore,
        db: Any,
        *,
        ntfy_topic: str = "",
        ntfy_server: str = "",
        engine_factory: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        broadcast: Optional[Callable[[Dict[str, Any]], Any]] = None,
        backfill: Optional[bool] = None,
    ):
        self.simbolo = simbolo
        self.provider_name = provider_name
        self.active_id = active_id
        self.visible = bool(visible)
        self.punto = float(punto or 0.00001)
        self.ntfy_topic = (ntfy_topic or "").strip()
        self.ntfy_server = (ntfy_server or "").strip()
        self.store = store
        self.db = db
        self.engine_factory = engine_factory
        self._broadcast = broadcast or manager.broadcast
        self.backfill = BACKFILL_ENABLED if backfill is None else bool(backfill)

        self.buffer: List[Dict[str, Any]] = []
        self.engine: Any = None
        self.connected = False
        self.running = False
        self.price: Optional[float] = None
        self.last_error: Optional[str] = None

        self._last_closed: Optional[int] = None
        self._last_tick_ts: Optional[float] = None
        self._sent_signals: set[str] = set()
        self._sinteticas_en_buffer = 0
        self._velas_suprimidas_restantes = 0
        self._backfill_info: Dict[str, Any] = {
            "usado": False,
            "ts": None,
            "sinteticas": 0,
            "total": 0,
            "error": None,
        }

    # ------------------------------------------------------------------ ciclo
    def start(self) -> None:
        """Carga histórico, construye el motor y precalienta sin emitir señales."""
        self.running = True
        try:
            rows = self.store.bars(self.provider_name, "M15", count=MAX_BUFFER)
            self._aplicar_historico(rows)
            self.connected = True
            self.last_error = None
        except Exception as e:
            self.connected = False
            self.last_error = str(e)
            logger.warning(f"[{self.simbolo}] Sin datos OTC al arrancar: {e}")

        self._actualizar_precio()
        if len(self.buffer) < MIN_M15_PARA_MOTOR:
            self._aplicar_backfill()
        self._construir_motor()
        if len(self.buffer) >= MIN_M15_PARA_MOTOR:
            self._precargar_motor()
        logger.info(
            f"[{self.simbolo}] OTC listo: {len(self.buffer)} velas M15 "
            f"({self._sinteticas_en_buffer} sintéticas), "
            f"visible={self.visible}, motor={'sí' if self.engine else 'no'}"
        )

    def _aplicar_historico(self, rows: List[Dict[str, Any]]) -> None:
        """Guarda la última racha continua de velas cerradas.

        Si el collector estuvo caído, el histórico contiene un hueco. El motor
        no debe interpretar como consecutivas velas separadas por horas, así
        que se conserva solo el segmento final sin cortes.
        """
        ahora = time.time()
        cerradas = sorted(
            (r for r in rows if r["time"] + TF_SECONDS["M15"] <= ahora),
            key=lambda r: r["time"],
        )
        segmento: List[Dict[str, Any]] = []
        for bar in cerradas:
            if segmento and bar["time"] - segmento[-1]["time"] > MAX_GAP_SECONDS:
                logger.warning(
                    f"[{self.simbolo}] Hueco de "
                    f"{(bar['time'] - segmento[-1]['time']) / 3600:.1f}h en el histórico; "
                    "se descarta el tramo anterior para el motor"
                )
                segmento = []
            segmento.append(bar)
        self.buffer = segmento[-MAX_BUFFER:]
        self._last_closed = self.buffer[-1]["time"] if self.buffer else None

    # ----------------------------------------------------------- backfill
    def _cargar_velas_chart(self) -> Optional[List[Dict[str, Any]]]:
        """Velas M15 sintéticas desde ``charts.d1``; None si no son usables."""
        if not self.backfill:
            return None
        try:
            quotes = self.store.chart_quotes(self.provider_name, "d1")
        except Exception as e:
            self._backfill_info["error"] = f"charts: {e}"
            return None
        if len(quotes) < 2:
            self._backfill_info["error"] = "charts sin datos"
            return None

        ultimo = max(int(q["timestamp"]) for q in quotes)
        edad = max(0.0, time.time() - ultimo)
        if edad > CHART_MAX_AGE:
            self._backfill_info["error"] = (
                f"charts atrasados {edad / 60.0:.0f} min"
            )
            return None

        velas = quotes_to_m15(quotes, now=time.time())
        if not velas:
            self._backfill_info["error"] = "charts sin velas cerradas"
            return None
        return velas

    def _aplicar_backfill(self) -> bool:
        """Completa el buffer con charts y lo deja listo para el motor.

        Solo se usa cuando faltan velas para el mínimo del motor o para
        puentear un hueco. Las velas reales siempre tienen prioridad.
        """
        ahora = time.time()
        sinteticas = self._cargar_velas_chart()
        if not sinteticas:
            return False
        try:
            reales = self.store.bars(
                self.provider_name,
                "M15",
                count=MAX_BUFFER,
                closed_only=True,
            )
        except Exception as e:
            self._backfill_info["error"] = f"reales: {e}"
            return False

        velas, n_sinteticas = fusionar_velas(
            reales,
            sinteticas,
            now=ahora,
            max_gap=MAX_GAP_SECONDS,
        )
        if len(velas) < MIN_M15_PARA_MOTOR or n_sinteticas <= 0:
            self._backfill_info["error"] = (
                f"charts insuficientes: {len(velas)} velas, "
                f"{n_sinteticas} sintéticas"
            )
            return False

        self.buffer = velas[-MAX_BUFFER:]
        self._last_closed = self.buffer[-1]["time"]
        self._sinteticas_en_buffer = sum(
            1 for bar in self.buffer if bar.get("sintetica")
        )
        self._velas_suprimidas_restantes = (
            BACKFILL_SUPPRESS_BARS if self._sinteticas_en_buffer else 0
        )
        self._backfill_info = {
            "usado": True,
            "ts": ahora,
            "sinteticas": self._sinteticas_en_buffer,
            "total": len(self.buffer),
            "error": None,
        }
        return True

    def _recuperar_hueco(self) -> bool:
        """Reconstruye buffer y motor usando charts tras un corte.

        Debe ejecutarse fuera del event loop: el motor crea el suyo propio.
        """
        self.engine = None
        if not self._aplicar_backfill():
            return False
        self._construir_motor()
        if self.engine is not None and len(self.buffer) >= MIN_M15_PARA_MOTOR:
            self._precargar_motor()
        # Si el motor falló, se conserva el buffer backfilleado: el reintento
        # del próximo poll lo reconstruye sin perder el calentamiento.
        return True

    def stop(self) -> None:
        self.running = False
        self.connected = False

    async def poll(self) -> None:
        """Busca velas M15 cerradas nuevas y las entrega al motor."""
        try:
            cerradas = await asyncio.to_thread(
                self.store.bars,
                self.provider_name,
                "M15",
                closed_only=True,
                since_open_time=self._last_closed,
            )
            tick = await asyncio.to_thread(self.store.last_tick, self.provider_name)
        except Exception as e:
            self.connected = False
            self.last_error = str(e)
            return

        self.connected = True
        self.last_error = None
        if tick:
            self.price = tick["price"]
            self._last_tick_ts = tick["ts"]
        else:
            self._actualizar_precio()

        # Arranque en frío: la DB no existía cuando arrancó el runtime. Se
        # carga el histórico y se precalienta el motor sin emitir señales.
        if not self.buffer and self._last_closed is None and cerradas:
            self._aplicar_historico(cerradas)
            if len(self.buffer) < MIN_M15_PARA_MOTOR:
                await asyncio.to_thread(self._aplicar_backfill)
            await asyncio.to_thread(self._construir_motor)
            if len(self.buffer) >= MIN_M15_PARA_MOTOR:
                await asyncio.to_thread(self._precargar_motor)
            return

        # Si un hueco anterior dejó el motor sin construir, reintentar antes de
        # procesar las velas nuevas. Sin esto el stream queda mudo para siempre.
        if self.engine is None and self.buffer:
            await asyncio.to_thread(self._construir_motor)

        ahora = time.time()
        for bar in cerradas:
            if self._last_closed is not None and bar["time"] <= self._last_closed:
                continue
            if self.buffer and bar["time"] - self.buffer[-1]["time"] > MAX_GAP_SECONDS:
                hueco_h = (bar["time"] - self.buffer[-1]["time"]) / 3600.0
                logger.warning(
                    f"[{self.simbolo}] Hueco de {hueco_h:.1f}h; "
                    "se intenta cubrir con charts"
                )
                recuperado = await asyncio.to_thread(self._recuperar_hueco)
                if recuperado:
                    logger.info(
                        f"[{self.simbolo}] Hueco de {hueco_h:.1f}h cubierto: "
                        f"{self._sinteticas_en_buffer} velas sintéticas, "
                        f"emisión silenciada "
                        f"{self._velas_suprimidas_restantes} velas"
                    )
                    if bar["time"] <= self._last_closed:
                        continue
                else:
                    logger.warning(
                        f"[{self.simbolo}] Sin charts utilizables "
                        f"({self._backfill_info.get('error')}); "
                        "se reinicia el buffer y el motor"
                    )
                    self.buffer = []
                    self.engine = None
                    # PivotRadarEngine crea su propio event loop para cargar
                    # la cola pendiente. Construirlo dentro del loop de la API
                    # falla con "Cannot run the event loop while another loop
                    # is running".
                    await asyncio.to_thread(self._construir_motor)
            self.buffer.append(bar)
            self.buffer = self.buffer[-MAX_BUFFER:]
            self._last_closed = bar["time"]
            if self._velas_suprimidas_restantes > 0:
                self._velas_suprimidas_restantes -= 1
                emitir = False
            else:
                emitir = (
                    len(self.buffer) >= MIN_M15_PARA_MOTOR
                    and bar["time"] + TF_SECONDS["M15"] >= ahora - MAX_EMIT_AGE
                )
            await self._on_bar_cerrada(emitir=emitir)

    # --------------------------------------------------------------- motor
    def _construir_motor(self) -> None:
        if self.engine is not None:
            return
        try:
            if self.engine_factory is not None:
                self.engine = self.engine_factory(
                    self.simbolo, {"provider_name": self.provider_name}
                )
                return
            from core.motor_v8 import PivotRadarEngine

            topic = self.ntfy_topic or os.getenv("IQ_PUBLIC_SIGNALS_NTFY_TOPIC", "").strip()
            server = self.ntfy_server or os.getenv("IQ_PUBLIC_SIGNALS_NTFY_SERVER", "").strip()
            data_dir = os.getenv("IQ_PUBLIC_ENGINE_DATA_DIR", "pivotradar_data")
            self.engine = PivotRadarEngine(
                symbol=self.simbolo,
                ntfy_topic=topic,
                ntfy_server=server or "https://ntfy.sh",
                modo_test=False,
                point=self.punto,
                broker_tz_offset_hours=int(os.getenv("IQ_PUBLIC_BROKER_TZ_OFFSET_HOURS", "0")),
                data_dir=os.path.join(data_dir, self.simbolo.lower()),
            )
        except Exception as e:
            self.engine = None
            self.last_error = f"motor: {e}"
            logger.error(f"[{self.simbolo}] No se pudo construir el motor PIVOT: {e}")

    def _df_m15(self) -> pd.DataFrame:
        if not self.buffer:
            return pd.DataFrame()
        df = pd.DataFrame(self.buffer)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
        return df[["open", "high", "low", "close", "volume"]]

    def _dfs_para_motor(self) -> tuple:
        """M15 del buffer + H1/H4/D1 resampleados del mismo histórico."""
        from kernel.feeds.csv_resample import resamplear_ohlc

        df_m15 = self._df_m15()
        if df_m15.empty:
            vacio = pd.DataFrame()
            return (df_m15, vacio, vacio, vacio)
        superiores = []
        for tf in ("H1", "H4", "D1"):
            try:
                superiores.append(resamplear_ohlc(df_m15, tf))
            except Exception as e:
                logger.error(f"[{self.simbolo}] Error resampleando {tf}: {e}")
                superiores.append(pd.DataFrame())
        return (df_m15, *superiores)

    def _precargar_motor(self) -> None:
        """Alimenta el histórico al motor sin emitir señales ni alertas."""
        if self.engine is None or len(self.buffer) < MIN_M15_PARA_MOTOR:
            return
        alertas = getattr(self.engine, "alertas", None)
        topic_backup = getattr(alertas, "ntfy_topic", "") if alertas is not None else ""
        if alertas is not None:
            alertas.ntfy_topic = ""
        try:
            dfs = self._dfs_para_motor()
            self.engine.on_data(*dfs)
            if alertas is not None:
                alertas.g_alert_queue = []
        except Exception as e:
            logger.error(f"[{self.simbolo}] Error precargando motor OTC: {e}")
        finally:
            if alertas is not None:
                alertas.ntfy_topic = topic_backup

        for sig in getattr(self.engine, "g_pending_signals", []) or []:
            if getattr(sig, "id", None):
                self._sent_signals.add(str(sig.id))
        logger.info(
            f"[{self.simbolo}] Motor OTC precargado; señales históricas silenciadas: "
            f"{len(self._sent_signals)}"
        )

    async def _on_bar_cerrada(self, emitir: bool = True) -> None:
        if self.engine is None:
            return
        # El motor envía ntfy por su cuenta dentro de ``on_data``. Durante el
        # catch-up o la supresión posterior a un backfill hay que silenciarlo,
        # igual que en la precarga: de lo contrario llegan alertas de señales
        # que el runtime no persiste ni considera nuevas.
        alertas = getattr(self.engine, "alertas", None)
        topic_backup = getattr(alertas, "ntfy_topic", "") if alertas is not None else ""
        if not emitir and alertas is not None:
            alertas.ntfy_topic = ""
        try:
            dfs = self._dfs_para_motor()
            await asyncio.to_thread(self.engine.on_data, *dfs)
        except Exception as e:
            logger.error(f"[{self.simbolo}] Error en detector PIVOT OTC: {e}")
            return
        finally:
            if not emitir and alertas is not None:
                alertas.ntfy_topic = topic_backup
                alertas.g_alert_queue = []

        if not emitir:
            # Catch-up: el motor se actualiza, pero sus señales históricas no
            # se persisten ni se difunden.
            for sig in list(getattr(self.engine, "g_pending_signals", []) or []):
                if getattr(sig, "id", None):
                    self._sent_signals.add(str(sig.id))
            return

        for payload in self._nuevas_senales_motor():
            try:
                await self._persistir(payload)
            except Exception as e:
                logger.error(f"[{self.simbolo}] Error persistiendo señal OTC: {e}")
            if not self.visible:
                continue
            await self._broadcast({
                "type": "signal",
                "data": payload,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            await manager.send_console_log({
                "ts": datetime.now(timezone.utc).isoformat(),
                "t": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                "level": "INFO",
                "cat": "PIVOT-OTC",
                "msg": (
                    f"Señal {'LONG' if payload.get('direccion') == 1 else 'SHORT'} "
                    f"{payload.get('asset')} @ {payload.get('precio')}"
                ),
            })

    def _nuevas_senales_motor(self) -> List[Dict[str, Any]]:
        if self.engine is None:
            return []
        nuevas: List[Dict[str, Any]] = []
        for sig in list(getattr(self.engine, "g_pending_signals", []) or []):
            if getattr(sig, "id", None) and str(sig.id) in self._sent_signals:
                continue
            payload = self._serializar_motor(sig)
            if payload:
                self._sent_signals.add(str(sig.id))
                nuevas.append(payload)
        return nuevas

    def _serializar_motor(self, sig: Any) -> Optional[Dict[str, Any]]:
        try:
            ts = (
                int(sig.entry_time.timestamp() * 1000)
                if getattr(sig, "entry_time", None)
                else int(datetime.now(timezone.utc).timestamp() * 1000)
            )
            precio = float(sig.entry_price)
            objetivo = float(sig.hipotesis_objetivo) if getattr(sig, "hipotesis_objetivo", None) else None
            invalidez = (
                float(sig.invalidez_estructural)
                if getattr(sig, "invalidez_estructural", None)
                else None
            )
            narrativa = self.engine.alertas.build_alert_text(sig)
            return {
                "id": str(sig.id),
                "ts": ts,
                "asset": getattr(sig, "symbol", None) or self.simbolo,
                "estrategia": "PIVOT",
                "etiqueta": getattr(sig, "tipo", None) or getattr(sig, "detector", "D0"),
                "direccion": int(sig.direction),
                "precio": precio,
                "expiracion_velas": int(getattr(sig, "hipotesis_expiry_velas", 0) or 0),
                "confianza": [
                    int(getattr(sig, "hipotesis_prob_min", 0) or 0),
                    int(getattr(sig, "hipotesis_prob_max", 0) or 0),
                ],
                "objetivo": objetivo,
                "invalidacion": invalidez,
                "narrativa": narrativa,
                "estado": "activa",
                "detectores": [getattr(sig, "detector", "D0")],
                "fuente": FUENTE,
                "datos_prueba": False,
            }
        except Exception as e:
            logger.error(f"[{self.simbolo}] Error serializando señal OTC: {e}")
            return None

    async def _persistir(self, sig: Dict[str, Any]) -> None:
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
            fuente=FUENTE,
        )
        logger.info(
            f"[{self.simbolo}] Señal OTC persistida: {sig['id']} "
            f"{sig['etiqueta']} dir={sig['direccion']}"
        )

    # -------------------------------------------------------------- lectura
    def _actualizar_precio(self) -> None:
        try:
            tick = self.store.last_tick(self.provider_name)
        except Exception:
            tick = None
        if tick:
            self.price = tick["price"]
            self._last_tick_ts = tick["ts"]
            return
        try:
            latest = self.store.latest_bar(self.provider_name, "M15")
        except Exception:
            latest = None
        if latest:
            self.price = latest["close"]

    def history(self, tf: str = "M15", count: int = 200) -> List[Dict[str, Any]]:
        """Velas para el chart, incluyendo la vela M15 en curso si existe."""
        from kernel.feeds.csv_resample import resamplear_ohlc

        rows = list(self.buffer)
        try:
            latest = self.store.latest_bar(self.provider_name, "M15")
        except Exception:
            latest = None
        if latest:
            if rows and latest["time"] == rows[-1]["time"]:
                rows[-1] = latest
            elif not rows or latest["time"] > rows[-1]["time"]:
                rows.append(latest)
        if not rows:
            return []

        tiempos_sinteticos = {
            int(r["time"]) for r in rows if r.get("sintetica")
        }
        df = pd.DataFrame(rows)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
        tf = str(tf).upper()
        if tf != "M15":
            try:
                df = resamplear_ohlc(df, tf)
            except Exception as e:
                logger.error(f"[{self.simbolo}] Error resampleando historial a {tf}: {e}")
                return []

        duracion = TF_SECONDS.get(tf, 0)
        out: List[Dict[str, Any]] = []
        for ts, row in df.tail(max(1, int(count))).iterrows():
            inicio = int(ts.timestamp())
            if duracion:
                sintetica = any(
                    inicio <= t < inicio + duracion for t in tiempos_sinteticos
                )
            else:
                sintetica = inicio in tiempos_sinteticos
            out.append({
                "time": inicio,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0) or 0),
                "sintetica": sintetica,
            })
        return out

    def status(self) -> Dict[str, Any]:
        ahora = time.time()
        last_bar_age = None
        if self._last_closed is not None:
            last_bar_age = max(0.0, ahora - (self._last_closed + TF_SECONDS["M15"]))
        tick_age = None
        if self._last_tick_ts is not None:
            tick_age = max(0.0, ahora - self._last_tick_ts)
        return {
            "simbolo": self.simbolo,
            "provider_name": self.provider_name,
            "active_id": self.active_id,
            "visible": self.visible,
            "connected": self.connected,
            "running": self.running,
            "price": self.price,
            "velas_buffer": len(self.buffer),
            "velas_sinteticas": sum(
                1 for bar in self.buffer if bar.get("sintetica")
            ),
            "emision_suprimida_velas": self._velas_suprimidas_restantes,
            "backfill": dict(self._backfill_info),
            "engine_ready": (
                self.engine is not None and len(self.buffer) >= MIN_M15_PARA_MOTOR
            ),
            "ntfy_topic": self.ntfy_topic or None,
            "ntfy_server": self.ntfy_server or None,
            "ntfy_ready": bool(
                self.engine
                and getattr(getattr(self.engine, "alertas", None), "ntfy_topic", "")
            ),
            "last_bar": _iso_utc(self._last_closed),
            "last_bar_age_s": last_bar_age,
            "last_tick_age_s": tick_age,
            "senales_enviadas": len(self._sent_signals),
            "last_error": self.last_error,
        }


class IQPublicRuntime:
    """Gestor multi-activo del feed OTC basado en la SQLite del collector."""

    def __init__(
        self,
        activos: Dict[str, Dict[str, Any]],
        db: Any,
        *,
        store: Optional[IQPublicStore] = None,
        engine_factory: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        broadcast: Optional[Callable[[Dict[str, Any]], Any]] = None,
        poll_seconds: Optional[float] = None,
        autopoll: bool = True,
        backfill: Optional[bool] = None,
    ):
        self.activos = activos
        self.db = db
        self.store = store or IQPublicStore(os.getenv("IQ_PUBLIC_DB", DEFAULT_DB))
        self.engine_factory = engine_factory
        self._broadcast = broadcast
        self.poll_seconds = float(poll_seconds or DEFAULT_POLL_SECONDS)
        self.autopoll = bool(autopoll)
        self.backfill = BACKFILL_ENABLED if backfill is None else bool(backfill)
        self.streams: Dict[str, AssetIQPublicStream] = {}
        self.started = False
        self._task: Optional[asyncio.Task] = None
        self._health: Optional[Dict[str, Any]] = None

    async def start(self) -> None:
        if self.started:
            return
        self.started = True
        for simbolo, cfg in self.activos.items():
            stream = AssetIQPublicStream(
                simbolo=simbolo,
                provider_name=cfg.get("provider_name") or simbolo.upper(),
                active_id=cfg.get("active_id"),
                visible=cfg.get("visible", False),
                punto=cfg.get("punto", 0.00001),
                ntfy_topic=cfg.get("ntfy_topic", ""),
                ntfy_server=cfg.get("ntfy_server", ""),
                store=self.store,
                db=self.db,
                engine_factory=self.engine_factory,
                broadcast=self._broadcast,
                backfill=self.backfill,
            )
            self.streams[simbolo] = stream
            try:
                await asyncio.to_thread(stream.start)
            except Exception as e:
                logger.error(f"[{simbolo}] Error arrancando stream OTC: {e}")
        try:
            self._health = await asyncio.to_thread(self.store.health)
        except Exception:
            self._health = None
        self._task = asyncio.create_task(self._poll_loop()) if self.autopoll else None
        logger.info(
            f"Runtime IQ OTC iniciado para {list(self.streams)} "
            f"(DB={self.store.path}, poll={self.poll_seconds:g}s)"
        )

    async def stop(self) -> None:
        self.started = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        for stream in self.streams.values():
            stream.stop()

    async def _poll_loop(self) -> None:
        try:
            while True:
                for stream in list(self.streams.values()):
                    try:
                        await stream.poll()
                    except Exception as e:
                        logger.error(f"[{stream.simbolo}] Error en poll OTC: {e}")
                try:
                    self._health = await asyncio.to_thread(self.store.health)
                except Exception:
                    self._health = None
                await asyncio.sleep(self.poll_seconds)
        except asyncio.CancelledError:
            raise

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": True,
            "db": str(self.store.path),
            "db_exists": self.store.path.exists(),
            "collector": self._health,
            "connected": any(s.connected for s in self.streams.values()),
            "assets": {s: st.status() for s, st in self.streams.items()},
        }
