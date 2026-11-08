# -*- coding: utf-8 -*-
"""
Kernel de PIVOT - Motor de Backtesting Profesional.
Ejecuta estrategias sobre datos históricos y calcula métricas de rendimiento.
"""
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from copy import deepcopy

from kernel.contrato import Contexto, Señal, ActivoInfo, Estrategia, Overlay, Metrica
from typing import Any
from kernel.feeds.csv import CSVFeed, MultiTimeframeFeed

logger = logging.getLogger(__name__)


@dataclass
class Operacion:
    """Representa una operación abierta o cerrada."""
    id_operacion: str
    señal: Señal
    simbolo: str
    direccion: int  # 1 = LONG, -1 = SHORT
    precio_entrada: float
    timestamp_entrada: datetime
    stop_loss: Optional[float]
    take_profit: Optional[float]
    
    # Estado
    precio_salida: Optional[float] = None
    timestamp_salida: Optional[datetime] = None
    razon_salida: str = ""  # "TP", "SL", "EXPIRED", "MANUAL"
    pnl_puntos: float = 0.0
    pnl_dinero: float = 0.0
    velas_en_operacion: int = 0
    max_favorable: float = 0.0  # Máximo precio favorable alcanzado
    max_adverso: float = 0.0   # Máximo precio adverso alcanzado
    
    def __post_init__(self):
        if self.id_operacion is None:
            self.id_operacion = f"OP_{self.timestamp_entrada.strftime('%Y%m%d_%H%M%S')}"


@dataclass
class ResultadoBacktest:
    """Resultados completos de un backtest."""
    # Configuración
    estrategia: str
    simbolo: str
    periodo_inicio: datetime
    periodo_fin: datetime
    timeframe_principal: str
    
    # Capital
    capital_inicial: float = 0.0
    capital_final: float = 0.0
    
    # Métricas principales
    total_operaciones: int = 0
    operaciones_totales: int = 0  # Alias para compatibilidad con tests
    operaciones_ganadoras: int = 0
    operaciones_perdedoras: int = 0
    operaciones_neutras: int = 0
    winrate: float = 0.0
    profit_factor: float = 0.0
    retorno_total: float = 0.0
    retorno_promedio: float = 0.0
    retorno_porcentual: float = 0.0  # Para compatibilidad con tests
    
    # Riesgo
    drawdown_maximo: float = 0.0
    drawdown_promedio: float = 0.0
    racha_ganadora_max: int = 0
    racha_perdedora_max: int = 0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    
    # Detalles
    operaciones: List[Operacion] = field(default_factory=list)
    equity_curve: List[Tuple[datetime, float]] = field(default_factory=list)
    metrics_extra: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario para serialización JSON."""
        return {
            "estrategia": self.estrategia,
            "simbolo": self.simbolo,
            "periodo_inicio": self.periodo_inicio.isoformat(),
            "periodo_fin": self.periodo_fin.isoformat(),
            "timeframe_principal": self.timeframe_principal,
            "total_operaciones": self.total_operaciones,
            "operaciones_ganadoras": self.operaciones_ganadoras,
            "operaciones_perdedoras": self.operaciones_perdedoras,
            "winrate": round(self.winrate, 2),
            "profit_factor": round(self.profit_factor, 2),
            "retorno_total": round(self.retorno_total, 2),
            "retorno_promedio": round(self.retorno_promedio, 2),
            "drawdown_maximo": round(self.drawdown_maximo, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "sortino_ratio": round(self.sortino_ratio, 2),
            "racha_ganadora_max": self.racha_ganadora_max,
            "racha_perdedora_max": self.racha_perdedora_max,
            "metrics_extra": self.metrics_extra,
        }


class BacktestEngine:
    """
    Motor de backtesting que ejecuta estrategias sobre datos históricos.
    
    Características:
    - Replay barra a barra
    - Gestión de operaciones (TP, SL, expiración)
    - Cálculo de métricas profesionales
    - Equity curve
    - Soporte multi-timeframe
    """
    
    def __init__(
        self,
        estrategia: Estrategia,
        activo: ActivoInfo,
        capital_inicial: float = 10000.0,
        riesgo_por_operacion: float = 0.01,
        slippage_pips: float = 0.0,
        comision_lote: float = 0.0,
        max_operaciones_simultaneas: int = 3,
        db: Any = None,
    ):
        """
        Inicializa el motor de backtest.
        
        Args:
            estrategia: Instancia de la estrategia a testear
            activo: Información del activo
            capital_inicial: Capital inicial
            riesgo_por_operacion: % del capital a arriesgar por operación
            slippage_pips: Slippage estimado en pips
            comision_lote: Comisión por lote
            max_operaciones_simultaneas: Máximo de operaciones simultáneas
            db: Instancia de Database para persistencia (opcional)
        """
        self.estrategia = estrategia
        self.activo = activo
        self.capital_inicial = capital_inicial
        self.riesgo_por_operacion = riesgo_por_operacion
        # Convertir pips a puntos (1 pip = 10 puntos para EURUSD)
        self.slippage_puntos = slippage_pips * activo.valor_pip * 10
        self.comision_puntos = comision_lote / activo.tamano_lote / activo.valor_pip / 10
        self.max_operaciones_simultaneas = max_operaciones_simultaneas
        self.db = db
        
        # Estado del backtest
        self.capital_actual = capital_inicial
        self.operaciones_abiertas: List[Operacion] = []
        self.operaciones_cerradas: List[Operacion] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.señales_generadas: List[Señal] = []
        
        # Contexto compartido
        self.contexto: Optional[Contexto] = None
    
    def _resolve_broker_tz(self) -> timezone:
        """Resuelve la timezone del broker (UTC+2 por defecto, como el motor live)."""
        tz = getattr(self.activo, "timezone", timezone.utc)
        if tz is timezone.utc:
            return timezone(timedelta(hours=2))
        return tz

    def _to_broker_time(self, bar_time: datetime) -> datetime:
        if bar_time is None or bar_time.year < 2000:
            return bar_time
        if bar_time.tzinfo is None:
            bar_time = bar_time.replace(tzinfo=timezone.utc)
        return bar_time.astimezone(self._broker_tz)

    def _get_session(self, bar_time: datetime) -> str:
        if bar_time is None or bar_time.year < 2000:
            return "OUT"
        bt = self._to_broker_time(bar_time)
        hour = bt.hour
        if 0 <= hour < 7:
            return "ASIA"
        if 7 <= hour < 13:
            return "LONDON"
        if 13 <= hour < 15:
            return "NY_OPEN"
        if 15 <= hour < 16:
            return "LONDON_CLOSE"
        if 16 <= hour < 21:
            return "NY"
        return "OUT"

    def _get_kill_zone(self, bar_time: datetime) -> str:
        if bar_time is None or bar_time.year < 2000:
            return "NONE"
        bt = self._to_broker_time(bar_time)
        hour = bt.hour
        minute = bt.minute
        if hour == 7 or hour == 8:
            return "LONDON_OPEN_KILL"
        if hour == 13 or (hour == 14 and minute <= 30):
            return "NY_OPEN_KILL"
        if 13 <= hour < 15:
            return "LONDON_NY_OVERLAP"
        return "NONE"

    @staticmethod
    def _get_trend_d1(g_ema50_d1_buffer, g_ema200_d1_buffer) -> str:
        if len(g_ema50_d1_buffer) < 2 or len(g_ema200_d1_buffer) < 2:
            return "NEUTRO"
        ema50 = g_ema50_d1_buffer[1]
        ema200 = g_ema200_d1_buffer[1]
        if ema50 == 0 or ema200 == 0:
            return "NEUTRO"
        eps = ema200 * 0.0005
        if ema50 > ema200 + eps:
            return "ALCISTA"
        if ema50 < ema200 - eps:
            return "BAJISTA"
        return "NEUTRO"

    @staticmethod
    def _get_regimen_vol(g_atr8_buffer, g_atr14_buffer, g_atr30_buffer) -> str:
        atr8 = g_atr8_buffer[0] if g_atr8_buffer else 0.0
        atr14 = g_atr14_buffer[0] if g_atr14_buffer else 0.0
        atr30 = g_atr30_buffer[0] if g_atr30_buffer else 0.0
        if atr14 == 0 or atr30 == 0:
            return "NORMAL"
        ratio_corto = atr8 / atr14
        ratio_largo = atr14 / atr30
        if ratio_largo < 0.6 and ratio_corto < 0.8:
            return "COMPRESION"
        elif ratio_largo > 1.5:
            return "EXTREMO"
        elif ratio_corto > 1.3:
            return "EXPANSION"
        return "NORMAL"

    def _crear_contexto(self, feeds: Dict[str, CSVFeed], bar: Optional[Dict[str, Any]] = None, pos: Optional[int] = None) -> Contexto:
        """
        Crea un contexto desde los feeds actuales SIN look-ahead.
        - M15 se recorta a la barra actual (ventana acotada).
        - H1/H4/D1 se derivan por resampling y se recortan al momento actual.
        - Los buffers de indicadores se pueblan desde columnas precalculadas (causales).
        - Se inyectan helpers reales de volumen, MSS H4 y zona premium/discount.
        """
        ref_timeframe = min(feeds.keys(), key=lambda tf: CSVFeed.TIMEFRAME_MAP.get(tf, 999999))
        ref_feed = feeds[ref_timeframe]
        df_full = ref_feed.df

        if pos is None:
            pos = ref_feed.idx
        if pos <= 0:
            pos = min(1, len(df_full))

        if bar is not None:
            current_time = bar["timestamp"]
        elif pos > 0 and pos <= len(df_full):
            current_time = df_full.index[pos - 1].to_pydatetime()
        else:
            current_time = datetime.now(timezone.utc)

        # M15 hasta la barra actual (incluyéndola), sin datos futuros
        n_m15 = df_full.index.searchsorted(pd.Timestamp(current_time), side="right")
        df_m15 = df_full.iloc[max(0, n_m15 - 500):n_m15]

        # Cache de columnas de indicadores (arrays numpy) para buffers baratos por barra
        if getattr(self, "_col_arrays", None) is None:
            cols = ["atr8", "atr14", "atr30", "ema21", "ema50", "rsi14"]
            self._col_arrays = {
                c: df_full[c].to_numpy(dtype=float) for c in cols if c in df_full.columns
            }
        col_arrays = self._col_arrays

        def _slice_tf(tf: str) -> Optional[pd.DataFrame]:
            full = self._precalc.get(tf)
            if full is None or full.empty:
                return None
            # FIX look-ahead (borde de hora/4h/día): usar side="left" para que
            # solo se incluyan velas YA CERRADAS (estrictamente < current_time).
            # side="right" incluía la vela H1/H4/D1 que recién abría en el instante
            # exacto del cambio de periodo (bug conocido, ~32% de barras afectadas).
            n = full.index.searchsorted(pd.Timestamp(current_time), side="left")
            if n <= 0:
                return None
            return full.iloc[max(0, n - 500):n]

        df_h1 = _slice_tf("H1")
        df_h4 = _slice_tf("H4")
        df_d1 = _slice_tf("D1")

        # Buffers de indicadores desde columnas precalculadas (causales, índice 0 = más reciente)
        BUF = 55

        def _buf(col: str) -> List[float]:
            arr = col_arrays.get(col)
            if arr is None or len(arr) == 0:
                return []
            end = min(n_m15, len(arr))
            start = max(0, end - BUF)
            seg = arr[start:end][::-1]
            return np.nan_to_num(seg, nan=0.0).tolist()

        g_atr8_buffer = _buf("atr8")
        g_atr14_buffer = _buf("atr14")
        g_atr30_buffer = _buf("atr30")
        g_ema21_buffer = _buf("ema21")
        g_ema50_buffer = _buf("ema50")
        g_rsi14_buffer = _buf("rsi14")

        # Buffers de EMAs D1/H4 para tendencia
        if getattr(self, "_ema_arrays", None) is None:
            self._ema_arrays = {
                tf: {k: v.to_numpy(dtype=float) for k, v in emas.items()}
                for tf, emas in getattr(self, "_precalc_emas", {}).items()
            }
        ema_arrays = self._ema_arrays

        g_ema50_d1_buffer: List[float] = []
        g_ema200_d1_buffer: List[float] = []
        g_ema20_h4_buffer: List[float] = []
        g_ema50_h4_buffer: List[float] = []

        if df_d1 is not None:
            d1_emas = ema_arrays.get("D1") or {}
            # FIX look-ahead: side="left" → solo velas D1 ya cerradas.
            n_d1 = self._precalc["D1"].index.searchsorted(pd.Timestamp(current_time), side="left")
            for key, buf in (("ema50", g_ema50_d1_buffer), ("ema200", g_ema200_d1_buffer)):
                arr = d1_emas.get(key)
                if arr is not None and n_d1 > 0:
                    seg = arr[max(0, n_d1 - 5):n_d1]
                    buf.extend([float(x) if not np.isnan(x) else 0.0 for x in seg[::-1]])

        if df_h4 is not None:
            h4_emas = ema_arrays.get("H4") or {}
            # FIX look-ahead: side="left" → solo velas H4 ya cerradas.
            n_h4 = self._precalc["H4"].index.searchsorted(pd.Timestamp(current_time), side="left")
            for key, buf in (("ema20", g_ema20_h4_buffer), ("ema50", g_ema50_h4_buffer)):
                arr = h4_emas.get(key)
                if arr is not None and n_h4 > 0:
                    seg = arr[max(0, n_h4 - 5):n_h4]
                    buf.extend([float(x) if not np.isnan(x) else 0.0 for x in seg[::-1]])

        ctx = Contexto(
            activo=self.activo,
            df_m15=df_m15,
            df_h1=df_h1,
            df_h4=df_h4,
            df_d1=df_d1,
            precio=float(df_m15["close"].iloc[-1]) if len(df_m15) else 0.0,
            tiempo=current_time,
            g_atr8_buffer=g_atr8_buffer,
            g_atr14_buffer=g_atr14_buffer,
            g_atr30_buffer=g_atr30_buffer,
            g_ema21_buffer=g_ema21_buffer,
            g_ema50_buffer=g_ema50_buffer,
            g_rsi14_buffer=g_rsi14_buffer,
            g_ema50_d1_buffer=g_ema50_d1_buffer,
            g_ema200_d1_buffer=g_ema200_d1_buffer,
            g_ema20_h4_buffer=g_ema20_h4_buffer,
            g_ema50_h4_buffer=g_ema50_h4_buffer,
            session=self._get_session(current_time),
            kill_zone=self._get_kill_zone(current_time),
            trend_d1=self._get_trend_d1(g_ema50_d1_buffer, g_ema200_d1_buffer),
            regimen_vol=self._get_regimen_vol(g_atr8_buffer, g_atr14_buffer, g_atr30_buffer),
            point=self.activo.punto,
            broker_tz_offset=self._broker_tz,
        )

        # Inyectar helpers reales (sobre datos recortados a la barra actual)
        ctx.get_volume_ratio = self._make_get_volume_ratio(df_m15)
        ctx.get_volume_ratio_cached = self._make_get_volume_ratio(df_m15)
        ctx.detect_mss_h4 = self._make_detect_mss_h4(df_h4)
        ctx.es_zona_premium_discount = self._make_es_zona_premium_discount(df_m15)
        ctx.evaluar_contexto_estructural = self._make_evaluar_contexto_estructural()

        return ctx

    @staticmethod
    def _make_get_volume_ratio(df: pd.DataFrame):
        """Crea la función get_volume_ratio sobre un df recortado a la barra actual."""
        if df is None or len(df) == 0:
            vol_arr = None
            n = 0
        else:
            n = len(df)
            col = "tick_volume" if "tick_volume" in df.columns else ("volume" if "volume" in df.columns else None)
            vol_arr = df[col].to_numpy(dtype=float) if col else None

        def _ivol(shift: int) -> int:
            if vol_arr is None or shift < 0 or shift >= n:
                return 0
            return int(vol_arr[n - (shift + 1)])

        def get_volume_ratio(bar_shift: int, n_lookback: int) -> float:
            if vol_arr is None or n == 0:
                return 1.0
            vol_signal = _ivol(bar_shift)
            if vol_signal <= 0:
                return 1.0
            total = 0
            count = 0
            for i in range(1, n_lookback + 1):
                v = _ivol(bar_shift + i)
                if v > 0:
                    total += v
                    count += 1
            if count == 0 or total <= 0:
                return 1.0
            return vol_signal / (total / count)

        return get_volume_ratio

    @staticmethod
    def _make_detect_mss_h4(df_h4: Optional[pd.DataFrame]):
        """Crea la función detect_mss_h4 sobre el H4 recortado a la barra actual."""
        if df_h4 is None or len(df_h4) < 50:
            h4_high = h4_low = h4_close = None
            n = 0
        else:
            n = len(df_h4)
            h4_high = df_h4["high"].to_numpy(dtype=float)
            h4_low = df_h4["low"].to_numpy(dtype=float)
            h4_close = df_h4["close"].to_numpy(dtype=float)

        def detect_mss_h4() -> Tuple[bool, int, str, float]:
            if h4_high is None or n < 50:
                return (False, 0, "", 0.0)
            max_scan = min(12, n - 3)
            for i in range(1, max_scan + 1):
                close_i = h4_close[n - (i + 1)]
                if close_i == 0:
                    continue
                prior_high = 0.0
                prior_low = 999999.0
                window_end = min(i + 1 + 20, n)
                for k in range(i + 1, window_end):
                    hk = h4_high[n - (k + 1)]
                    lk = h4_low[n - (k + 1)]
                    if hk == 0 or lk == 0:
                        continue
                    if hk > prior_high:
                        prior_high = hk
                    if lk < prior_low:
                        prior_low = lk
                if prior_high == 0 or prior_low >= 999999.0:
                    continue
                if close_i > prior_high:
                    return (True, i, "ALCISTA", prior_high)
                if close_i < prior_low:
                    return (True, i, "BAJISTA", prior_low)
            return (False, 0, "", 0.0)

        return detect_mss_h4

    @staticmethod
    def _make_es_zona_premium_discount(df: pd.DataFrame):
        """Crea la función es_zona_premium_discount sobre el M15 recortado."""
        if df is None or len(df) == 0:
            high_arr = low_arr = None
            n = 0
        else:
            n = len(df)
            high_arr = df["high"].to_numpy(dtype=float)
            low_arr = df["low"].to_numpy(dtype=float)

        def es_zona_premium_discount(nivel: float) -> Tuple[bool, str]:
            if high_arr is None or n == 0:
                return (False, "NEUTRO")
            max_high = 0.0
            min_low = 999999.0
            for i in range(1, min(51, n)):
                h = high_arr[n - (i + 1)]
                l = low_arr[n - (i + 1)]
                if h == 0 or l == 0:
                    break
                if h > max_high:
                    max_high = h
                if l < min_low:
                    min_low = l
            if max_high > 0 and min_low < 999999.0 and max_high > min_low:
                mid = (max_high + min_low) / 2.0
                return (True, "PREMIUM" if nivel > mid else "DISCOUNT")
            return (False, "NEUTRO")

        return es_zona_premium_discount

    @staticmethod
    def _make_evaluar_contexto_estructural():
        """Stub conservador; los detectores no lo usan en el path de backtest."""
        def evaluar_contexto_estructural(direction: int, nivel: float, detector: str, trend_d1: str) -> Tuple[float, float]:
            return (50.0, 0.0)

        return evaluar_contexto_estructural
    
    def _aplicar_slippage(self, precio: float, direccion: int) -> float:
        """Aplica slippage al precio de entrada."""
        ajuste = self.slippage_puntos * self.activo.punto
        if direccion == 1:  # LONG - entrar más caro
            return precio + ajuste
        else:  # SHORT - entrar más barato
            return precio - ajuste
    
    def _calcular_tamano_posicion(self, precio_entrada: float, stop_loss: float) -> float:
        """Calcula el tamaño de posición basado en el riesgo."""
        if stop_loss is None or precio_entrada == stop_loss:
            return 0.0
        
        riesgo_puntos = abs(precio_entrada - stop_loss) / self.activo.punto
        riesgo_dinero = self.capital_actual * self.riesgo_por_operacion
        
        if riesgo_puntos == 0:
            return 0.0
        
        lotes = riesgo_dinero / (riesgo_puntos * self.activo.punto * self.activo.contract_size)
        return round(lotes, 2)
    
    def _abrir_operacion(self, señal: Señal, precio_entrada: float) -> Operacion:
        """Abre una nueva operación."""
        op = Operacion(
            id_operacion=None,
            señal=señal,
            simbolo=señal.simbolo,
            direccion=señal.direccion,
            precio_entrada=precio_entrada,
            timestamp_entrada=señal.tiempo,
            stop_loss=señal.stop_loss,
            take_profit=señal.take_profit,
        )
        
        self.operaciones_abiertas.append(op)
        return op
    
    def _cerrar_operacion(
        self,
        operacion: Operacion,
        precio_salida: float,
        timestamp_salida: datetime,
        razon: str,
    ):
        """Cierra una operación y calcula PnL."""
        # Calcular PnL en puntos
        if operacion.direccion == 1:  # LONG
            pnl_puntos = (precio_salida - operacion.precio_entrada) / self.activo.punto
        else:  # SHORT
            pnl_puntos = (operacion.precio_entrada - precio_salida) / self.activo.punto
        
        # Restar comisión
        pnl_puntos -= self.comision_puntos * 2  # Entrada + salida
        
        # Calcular PnL en dinero
        operacion.pnl_dinero = pnl_puntos * self.activo.punto * self.activo.contract_size
        
        # Actualizar operación
        operacion.precio_salida = precio_salida
        operacion.timestamp_salida = timestamp_salida
        operacion.razon_salida = razon
        operacion.pnl_puntos = pnl_puntos
        
        # Mover a cerradas
        self.operaciones_abiertas.remove(operacion)
        self.operaciones_cerradas.append(operacion)
        
        # Actualar capital
        self.capital_actual += operacion.pnl_dinero
        
        # Fase 8.3: Registrar en dataset ML para entrenamiento futuro (Tarea 10)
        if self.db is not None:
            try:
                detectores = getattr(operacion.señal, 'contexto', {}).get('detectores', [])
                
                self.db.guardar_resultado_operacion({
                    "timestamp_entrada": operacion.timestamp_entrada.isoformat(),
                    "timestamp_salida": operacion.timestamp_salida.isoformat(),
                    "simbolo": operacion.simbolo,
                    "direccion": operacion.direccion,
                    "detectores_activos": detectores,
                    "pnl_puntos": operacion.pnl_puntos,
                    "razon_salida": operacion.razon_salida,
                    "fue_ganadora": operacion.pnl_puntos > 0,
                    "pnl_dinero": operacion.pnl_dinero,
                })
            except Exception as e:
                logger.error(f"Error persistiendo operación ML: {e}")
    
    def _gestionar_operaciones_abiertas(self, bar_actual: Dict[str, Any]):
        """Gestiona las operaciones abiertas contra la vela actual."""
        high = bar_actual["high"]
        low = bar_actual["low"]
        close = bar_actual["close"]
        timestamp = bar_actual["timestamp"]
        
        # Iterar sobre copia para poder modificar la lista original
        for operacion in self.operaciones_abiertas[:]:
            operacion.velas_en_operacion += 1
            
            # Actualizar máximos favorables/adversos
            if operacion.direccion == 1:  # LONG
                operacion.max_favorable = max(operacion.max_favorable, high)
                operacion.max_adverso = min(operacion.max_adverso, low)
                
                # Verificar TP
                if operacion.take_profit and high >= operacion.take_profit:
                    self._cerrar_operacion(operacion, operacion.take_profit, timestamp, "TP")
                    continue
                
                # Verificar SL
                if operacion.stop_loss and low <= operacion.stop_loss:
                    self._cerrar_operacion(operacion, operacion.stop_loss, timestamp, "SL")
                    continue
                
            else:  # SHORT
                operacion.max_favorable = min(operacion.max_favorable, low)
                operacion.max_adverso = max(operacion.max_adverso, high)
                
                # Verificar TP
                if operacion.take_profit and low <= operacion.take_profit:
                    self._cerrar_operacion(operacion, operacion.take_profit, timestamp, "TP")
                    continue
                
                # Verificar SL
                if operacion.stop_loss and high >= operacion.stop_loss:
                    self._cerrar_operacion(operacion, operacion.stop_loss, timestamp, "SL")
                    continue
            
            # Verificar expiración por velas
            if operacion.velas_en_operacion >= operacion.señal.expiracion_velas:
                self._cerrar_operacion(operacion, close, timestamp, "EXPIRED")
                continue
    
    def _calcular_metricas(self) -> ResultadoBacktest:
        """Calcula todas las métricas del backtest."""
        resultado = ResultadoBacktest(
            estrategia=self.estrategia.nombre,
            simbolo=self.activo.simbolo,
            periodo_inicio=self.equity_curve[0][0] if self.equity_curve else datetime(1970, 1, 1),
            periodo_fin=self.equity_curve[-1][0] if self.equity_curve else datetime(1970, 1, 1),
            timeframe_principal="M15",  # Debería venir de los feeds
            capital_inicial=self.capital_inicial,
            capital_final=self.capital_actual,
            operaciones=self.operaciones_cerradas,
            equity_curve=self.equity_curve,
        )
        
        if not self.operaciones_cerradas:
            return resultado
        
        # Contar ganadoras/perdedoras
        gains = [op.pnl_dinero for op in self.operaciones_cerradas if op.pnl_dinero > 0]
        losses = [op.pnl_dinero for op in self.operaciones_cerradas if op.pnl_dinero < 0]
        neutral = [op for op in self.operaciones_cerradas if op.pnl_dinero == 0]
        
        resultado.operaciones_ganadoras = len(gains)
        resultado.operaciones_perdedoras = len(losses)
        resultado.operaciones_neutras = len(neutral)
        resultado.total_operaciones = len(self.operaciones_cerradas)
        resultado.operaciones_totales = resultado.total_operaciones  # Alias
        
        # Winrate
        if resultado.total_operaciones > 0:
            resultado.winrate = (resultado.operaciones_ganadoras / resultado.total_operaciones) * 100
        
        # Profit Factor
        total_gains = sum(gains)
        total_losses = abs(sum(losses))
        if total_losses > 0:
            resultado.profit_factor = total_gains / total_losses
        elif total_gains > 0:
            resultado.profit_factor = float('inf')
        
        # Retorno
        resultado.retorno_total = ((self.capital_actual - self.capital_inicial) / self.capital_inicial) * 100
        resultado.retorno_promedio = resultado.retorno_total / resultado.total_operaciones if resultado.total_operaciones > 0 else 0
        resultado.retorno_porcentual = resultado.retorno_total  # Alias para tests
        
        # Drawdown
        if len(self.equity_curve) > 1:
            equity_values = [e[1] for e in self.equity_curve]
            peak = equity_values[0]
            drawdowns = []
            
            for value in equity_values:
                if value > peak:
                    peak = value
                drawdown = (peak - value) / peak * 100 if peak > 0 else 0
                drawdowns.append(drawdown)
            
            resultado.drawdown_maximo = max(drawdowns)
            resultado.drawdown_promedio = sum(drawdowns) / len(drawdowns) if drawdowns else 0
        
        # Rachas
        current_streak = 0
        max_win_streak = 0
        max_loss_streak = 0
        last_result = None
        
        for op in self.operaciones_cerradas:
            if op.pnl_dinero > 0:
                if last_result == "win":
                    current_streak += 1
                else:
                    current_streak = 1
                last_result = "win"
                max_win_streak = max(max_win_streak, current_streak)
            elif op.pnl_dinero < 0:
                if last_result == "loss":
                    current_streak += 1
                else:
                    current_streak = 1
                last_result = "loss"
                max_loss_streak = max(max_loss_streak, current_streak)
            else:
                current_streak = 0
                last_result = None
        
        resultado.racha_ganadora_max = max_win_streak
        resultado.racha_perdedora_max = max_loss_streak
        
        # Sharpe Ratio (simplificado)
        if len(self.equity_curve) > 1:
            returns = []
            for i in range(1, len(self.equity_curve)):
                prev_eq = self.equity_curve[i-1][1]
                curr_eq = self.equity_curve[i][1]
                if prev_eq > 0:
                    returns.append((curr_eq - prev_eq) / prev_eq)
            
            if returns and np.std(returns) > 0:
                avg_return = np.mean(returns)
                std_return = np.std(returns)
                resultado.sharpe_ratio = (avg_return / std_return) * np.sqrt(252)  # Annualizado
                
                # Sortino Ratio (solo desviación negativa)
                downside_returns = [r for r in returns if r < 0]
                if downside_returns:
                    downside_std = np.std(downside_returns)
                    if downside_std > 0:
                        resultado.sortino_ratio = (avg_return / downside_std) * np.sqrt(252)
        
        return resultado
    
    def ejecutar(
        self,
        feeds: Dict[str, CSVFeed],
        params_estrategia: Optional[Dict[str, Any]] = None,
    ) -> ResultadoBacktest:
        """
        Ejecuta el backtest completo.
        
        Args:
            feeds: Diccionario {timeframe: CSVFeed} con los datos
            params_estrategia: Parámetros para la estrategia
            
        Returns:
            ResultadoBacktest con métricas completas
        """
        # Resetear estado
        self.capital_actual = self.capital_inicial
        self.operaciones_abiertas = []
        self.operaciones_cerradas = []
        self.equity_curve = []
        self.señales_generadas = []
        self._col_arrays = None
        self._ema_arrays = None
        
        # Setup de la estrategia
        self.estrategia.setup(params_estrategia or {}, self.activo)
        
        # Obtener feed de referencia (el de menor timeframe)
        ref_timeframe = min(feeds.keys(), key=lambda tf: CSVFeed.TIMEFRAME_MAP.get(tf, 999999))
        ref_feed = feeds[ref_timeframe]
        
        # Precalcular timeframes superiores UNA sola vez desde todo el M15.
        # NO es look-ahead: cada barra recorta estos DataFrames a su timestamp actual.
        from kernel.feeds.csv_resample import resamplear_ohlc
        df_full = ref_feed.df
        self._precalc: Dict[str, Optional[pd.DataFrame]] = {}
        for tf in ["H1", "H4", "D1"]:
            if tf == ref_timeframe:
                continue
            try:
                self._precalc[tf] = resamplear_ohlc(df_full, tf)
            except Exception as e:
                logger.warning(f"No se pudo precalcular {tf}: {e}")
                self._precalc[tf] = None
        
        # Precalcular series de EMA para tendencias D1/H4 (también recortadas por barra)
        self._precalc_emas: Dict[str, Dict[str, pd.Series]] = {}
        for tf in ["H1", "H4", "D1"]:
            df_tf = self._precalc.get(tf)
            if df_tf is None or df_tf.empty:
                continue
            close = df_tf["close"]
            emas: Dict[str, pd.Series] = {}
            if tf == "D1":
                emas["ema50"] = close.ewm(span=50, adjust=False).mean()
                emas["ema200"] = close.ewm(span=200, adjust=False).mean()
            if tf == "H4":
                emas["ema20"] = close.ewm(span=20, adjust=False).mean()
                emas["ema50"] = close.ewm(span=50, adjust=False).mean()
            self._precalc_emas[tf] = emas
        
        self._broker_tz = self._resolve_broker_tz()
        
        # Iterar barra a barra
        for bar in ref_feed.iter_barras():
            pos = ref_feed.idx
            
            # Construir contexto con datos solo hasta la barra actual (sin look-ahead)
            self.contexto = self._crear_contexto(feeds, bar=bar, pos=pos)
            self.contexto.precio = bar["close"]
            self.contexto.tiempo = bar["timestamp"]
            
            # Ejecutar estrategia
            señales = self.estrategia.detectar(self.contexto)
            
            # Procesar señales
            for señal in señales:
                señal.tiempo = bar["timestamp"]
                señal.precio = bar["close"]
                self.señales_generadas.append(señal)
                
                # Abrir operación si hay espacio
                if len(self.operaciones_abiertas) < self.max_operaciones_simultaneas:  # Máximo configurable
                    precio_entrada = self._aplicar_slippage(bar["close"], señal.direccion)
                    self._abrir_operacion(señal, precio_entrada)
            
            # Gestionar operaciones abiertas
            self._gestionar_operaciones_abiertas(bar)
            
            # Registrar equity
            equity_actual = self.capital_actual + sum(
                self._calcular_equity_operacion(op, bar)
                for op in self.operaciones_abiertas
            )
            self.equity_curve.append((bar["timestamp"], equity_actual))
        
        # Calcular métricas finales
        return self._calcular_metricas()
    
    def _calcular_equity_operacion(self, operacion: Operacion, bar: Dict[str, Any]) -> float:
        """Calcula el equity flotante de una operación abierta."""
        close = bar["close"]
        
        if operacion.direccion == 1:  # LONG
            pnl_puntos = (close - operacion.precio_entrada) / self.activo.punto
        else:  # SHORT
            pnl_puntos = (operacion.precio_entrada - close) / self.activo.punto
        
        return pnl_puntos * self.activo.punto * self.activo.contract_size


def run_backtest(
    estrategia: Estrategia,
    activo: ActivoInfo,
    data_path: str,
    timeframe: str = "M15",
    params: Optional[Dict[str, Any]] = None,
    capital: float = 10000.0,
    riesgo: float = 0.01,
) -> ResultadoBacktest:
    """
    Función helper para ejecutar un backtest rápidamente.
    
    Args:
        estrategia: Instancia de estrategia
        activo: Información del activo
        data_path: Ruta al CSV con datos
        timeframe: Timeframe principal
        params: Parámetros para la estrategia
        capital: Capital inicial
        riesgo: Riesgo por operación
        
    Returns:
        ResultadoBacktest completo
    """
    # Crear feed
    feed = CSVFeed(path=data_path, timeframe=timeframe, symbol=activo.simbolo)
    
    # Crear engine
    engine = BacktestEngine(
        estrategia=estrategia,
        activo=activo,
        capital_inicial=capital,
        riesgo_por_operacion=riesgo,
    )
    
    # Ejecutar
    return engine.ejecutar(feeds={timeframe: feed}, params_estrategia=params)
