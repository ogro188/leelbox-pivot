# -*- coding: utf-8 -*-
"""
BinaryBacktestEngine - Motor de backtesting para opciones binarias.
Simula compra de contratos con expiración temporal y payout fijo.
"""
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timezone, timedelta, date
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from copy import deepcopy

from kernel.contrato import (
    Contexto, Señal, ActivoInfo, Estrategia, 
    BinarySeñal, BinaryActivoInfo, BinaryResultado, BinaryRiskConfig, BinaryRiskMode
)
from kernel.binary.risk import BinaryRiskManager, calculate_expected_value
from kernel.feeds.csv import CSVFeed, MultiTimeframeFeed

logger = logging.getLogger(__name__)


@dataclass
class BinaryOperacion:
    """Representa un contrato binario abierto o cerrado."""
    id_operacion: str
    señal: BinarySeñal
    simbolo: str
    direccion: int  # 1 = CALL, -1 = PUT
    precio_entrada: float
    timestamp_entrada: datetime
    expiry_timestamp: datetime
    expiry_minutes: int
    payout_pct: float
    contract_amount: float
    contract_count: int
    
    # Estado
    precio_expiry: Optional[float] = None
    timestamp_expiry: Optional[datetime] = None
    resultado: str = ""  # "WIN", "LOSS"
    pnl_dinero: float = 0.0
    pnl_pct: float = 0.0
    
    def __post_init__(self):
        if self.id_operacion is None:
            self.id_operacion = f"BIN_{self.timestamp_entrada.strftime('%Y%m%d_%H%M%S')}"


class BinaryBacktestEngine:
    """
    Motor de backtesting para opciones binarias.
    
    Características:
    - Replay barra a barra (M15 base)
    - Simulación de contratos con expiración temporal exacta
    - Payout fijo por contrato (win = amount * payout, loss = -amount)
    - Múltiples modos de risk management (fixed, martingale, kelly, etc.)
    - Límites diarios y de exposición
    - Equity curve y métricas específicas binarias
    """
    
    def __init__(
        self,
        estrategia: Estrategia,
        activo: BinaryActivoInfo,
        capital_inicial: float = 10000.0,
        risk_config: Optional[BinaryRiskConfig] = None,
        db: Any = None,
    ):
        """
        Inicializa el motor de backtest binario.
        
        Args:
            estrategia: Instancia de estrategia (debe generar BinarySeñal)
            activo: BinaryActivoInfo con payout_table
            capital_inicial: Capital inicial en USD
            risk_config: Configuración de riesgo (default: fixed $10)
            db: Instancia de Database para persistencia (opcional)
        """
        self.estrategia = estrategia
        self.activo = activo
        self.capital_inicial = capital_inicial
        self.db = db
        
        # Risk manager
        if risk_config is None:
            risk_config = BinaryRiskConfig()
        # Aplicar límites del activo
        risk_config.min_contract = getattr(activo, 'min_contract', 1.0)
        risk_config.max_contract = getattr(activo, 'max_contract', 10000.0)
        self.risk_manager = BinaryRiskManager(risk_config, capital_inicial)
        
        # Estado del backtest
        self.capital_actual = capital_inicial
        self.operaciones_abiertas: List[BinaryOperacion] = []
        self.operaciones_cerradas: List[BinaryOperacion] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.señales_generadas: List[BinarySeñal] = []
        
        # Contexto compartido
        self.contexto: Optional[Contexto] = None
        
        # Broker timezone (para expiraciones correctas)
        self._broker_tz = self._resolve_broker_tz()
    
    def _resolve_broker_tz(self) -> timezone:
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
    
    def _crear_contexto(self, feeds: Dict[str, CSVFeed], bar: Dict[str, Any], pos: int) -> Contexto:
        """Crea contexto desde feeds (igual que BacktestEngine pero adaptado)."""
        # Reutilizar lógica de _crear_contexto del BacktestEngine estándar
        # pero adaptado para binarias (no necesita SL/TP logic en contexto)
        ref_timeframe = min(feeds.keys(), key=lambda tf: CSVFeed.TIMEFRAME_MAP.get(tf, 999999))
        ref_feed = feeds[ref_timeframe]
        df_full = ref_feed.df
        
        current_time = bar["timestamp"]
        n_m15 = df_full.index.searchsorted(pd.Timestamp(current_time), side="right")
        df_m15 = df_full.iloc[max(0, n_m15 - 500):n_m15]
        
        # Cache de indicadores
        if getattr(self, "_col_arrays", None) is None:
            cols = ["atr8", "atr14", "atr30", "ema21", "ema50", "rsi14"]
            self._col_arrays = {
                c: df_full[c].to_numpy(dtype=float) for c in cols if c in df_full.columns
            }
        col_arrays = self._col_arrays
        
        def _buf(col: str) -> List[float]:
            arr = col_arrays.get(col)
            if arr is None or len(arr) == 0:
                return []
            end = min(n_m15, len(arr))
            start = max(0, end - 55)
            seg = arr[start:end][::-1]
            return np.nan_to_num(seg, nan=0.0).tolist()
        
        g_atr8_buffer = _buf("atr8")
        g_atr14_buffer = _buf("atr14")
        g_atr30_buffer = _buf("atr30")
        g_ema21_buffer = _buf("ema21")
        g_ema50_buffer = _buf("ema50")
        g_rsi14_buffer = _buf("rsi14")
        
        # Resample H1/H4/D1 (cacheado)
        if getattr(self, "_precalc", None) is None:
            from kernel.feeds.csv_resample import resamplear_ohlc
            self._precalc: Dict[str, Optional[pd.DataFrame]] = {}
            for tf in ["H1", "H4", "D1"]:
                if tf == ref_timeframe:
                    continue
                try:
                    self._precalc[tf] = resamplear_ohlc(df_full, tf)
                except Exception as e:
                    logger.warning(f"No se pudo precalcular {tf}: {e}")
                    self._precalc[tf] = None
        
        def _slice_tf(tf: str) -> Optional[pd.DataFrame]:
            full = self._precalc.get(tf)
            if full is None or full.empty:
                return None
            # FIX look-ahead: side="left" -> solo velas YA CERRADAS
            n = full.index.searchsorted(pd.Timestamp(current_time), side="left")
            if n <= 0:
                return None
            return full.iloc[max(0, n - 500):n]
        
        df_h1 = _slice_tf("H1")
        df_h4 = _slice_tf("H4")
        df_d1 = _slice_tf("D1")
        
        # EMAs D1/H4
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
            n_d1 = self._precalc["D1"].index.searchsorted(pd.Timestamp(current_time), side="left")
            for key, buf in (("ema50", g_ema50_d1_buffer), ("ema200", g_ema200_d1_buffer)):
                arr = d1_emas.get(key)
                if arr is not None and n_d1 > 0:
                    seg = arr[max(0, n_d1 - 5):n_d1]
                    buf.extend([float(x) if not np.isnan(x) else 0.0 for x in seg[::-1]])
        
        if df_h4 is not None:
            h4_emas = ema_arrays.get("H4") or {}
            n_h4 = self._precalc["H4"].index.searchsorted(pd.Timestamp(current_time), side="left")
            for key, buf in (("ema20", g_ema20_h4_buffer), ("ema50", g_ema50_h4_buffer)):
                arr = h4_emas.get(key)
                if arr is not None and n_h4 > 0:
                    seg = arr[max(0, n_h4 - 5):n_h4]
                    buf.extend([float(x) if not np.isnan(x) else 0.0 for x in seg[::-1]])
        
        # Helpers de volumen, MSS, zona
        def _make_get_volume_ratio(df: pd.DataFrame):
            if df is None or len(df) == 0:
                return lambda *a, **k: 1.0
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
                total = 0; count = 0
                for i in range(1, n_lookback + 1):
                    v = _ivol(bar_shift + i)
                    if v > 0:
                        total += v; count += 1
                if count == 0 or total <= 0:
                    return 1.0
                return vol_signal / (total / count)
            return get_volume_ratio
        
        def _make_detect_mss_h4(df_h4: Optional[pd.DataFrame]):
            if df_h4 is None or len(df_h4) < 50:
                return lambda: (False, 0, "", 0.0)
            n = len(df_h4)
            h4_high = df_h4["high"].to_numpy(dtype=float)
            h4_low = df_h4["low"].to_numpy(dtype=float)
            h4_close = df_h4["close"].to_numpy(dtype=float)
            def detect_mss_h4() -> Tuple[bool, int, str, float]:
                if n < 50:
                    return (False, 0, "", 0.0)
                max_scan = min(12, n - 3)
                for i in range(1, max_scan + 1):
                    close_i = h4_close[n - (i + 1)]
                    if close_i == 0: continue
                    prior_high = 0.0; prior_low = 999999.0
                    window_end = min(i + 1 + 20, n)
                    for k in range(i + 1, window_end):
                        hk = h4_high[n - (k + 1)]
                        lk = h4_low[n - (k + 1)]
                        if hk == 0 or lk == 0: continue
                        if hk > prior_high: prior_high = hk
                        if lk < prior_low: prior_low = lk
                    if prior_high == 0 or prior_low >= 999999.0: continue
                    if close_i > prior_high:
                        return (True, i, "ALCISTA", prior_high)
                    if close_i < prior_low:
                        return (True, i, "BAJISTA", prior_low)
                return (False, 0, "", 0.0)
            return detect_mss_h4
        
        def _make_es_zona_premium_discount(df: pd.DataFrame):
            if df is None or len(df) == 0:
                return lambda nivel: (False, "NEUTRO")
            n = len(df)
            high_arr = df["high"].to_numpy(dtype=float)
            low_arr = df["low"].to_numpy(dtype=float)
            def es_zona_premium_discount(nivel: float) -> Tuple[bool, str]:
                max_high = 0.0; min_low = 999999.0
                for i in range(1, min(51, n)):
                    h = high_arr[n - (i + 1)]
                    l = low_arr[n - (i + 1)]
                    if h == 0 or l == 0: break
                    if h > max_high: max_high = h
                    if l < min_low: min_low = l
                if max_high > 0 and min_low < 999999.0 and max_high > min_low:
                    mid = (max_high + min_low) / 2.0
                    return (True, "PREMIUM" if nivel > mid else "DISCOUNT")
                return (False, "NEUTRO")
            return es_zona_premium_discount
        
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
        
        ctx.get_volume_ratio = _make_get_volume_ratio(df_m15)
        ctx.get_volume_ratio_cached = _make_get_volume_ratio(df_m15)
        ctx.detect_mss_h4 = _make_detect_mss_h4(df_h4)
        ctx.es_zona_premium_discount = _make_es_zona_premium_discount(df_m15)
        ctx.evaluar_contexto_estructural = lambda *a: (50.0, 0.0)
        
        return ctx
    
    def _get_session(self, bar_time: datetime) -> str:
        if bar_time is None or bar_time.year < 2000:
            return "OUT"
        bt = self._to_broker_time(bar_time)
        hour = bt.hour
        if 0 <= hour < 7: return "ASIA"
        if 7 <= hour < 13: return "LONDON"
        if 13 <= hour < 15: return "NY_OPEN"
        if 15 <= hour < 16: return "LONDON_CLOSE"
        if 16 <= hour < 21: return "NY"
        return "OUT"
    
    def _get_kill_zone(self, bar_time: datetime) -> str:
        if bar_time is None or bar_time.year < 2000:
            return "NONE"
        bt = self._to_broker_time(bar_time)
        hour = bt.hour; minute = bt.minute
        if hour == 7 or hour == 8: return "LONDON_OPEN_KILL"
        if hour == 13 or (hour == 14 and minute <= 30): return "NY_OPEN_KILL"
        if 13 <= hour < 15: return "LONDON_NY_OVERLAP"
        return "NONE"
    
    @staticmethod
    def _get_trend_d1(g_ema50_d1_buffer, g_ema200_d1_buffer) -> str:
        if len(g_ema50_d1_buffer) < 2 or len(g_ema200_d1_buffer) < 2:
            return "NEUTRO"
        ema50 = g_ema50_d1_buffer[1]; ema200 = g_ema200_d1_buffer[1]
        if ema50 == 0 or ema200 == 0: return "NEUTRO"
        eps = ema200 * 0.0005
        if ema50 > ema200 + eps: return "ALCISTA"
        if ema50 < ema200 - eps: return "BAJISTA"
        return "NEUTRO"
    
    @staticmethod
    def _get_regimen_vol(g_atr8_buffer, g_atr14_buffer, g_atr30_buffer) -> str:
        atr8 = g_atr8_buffer[0] if g_atr8_buffer else 0.0
        atr14 = g_atr14_buffer[0] if g_atr14_buffer else 0.0
        atr30 = g_atr30_buffer[0] if g_atr30_buffer else 0.0
        if atr14 == 0 or atr30 == 0: return "NORMAL"
        ratio_corto = atr8 / atr14
        ratio_largo = atr14 / atr30
        if ratio_largo < 0.6 and ratio_corto < 0.8: return "COMPRESION"
        elif ratio_largo > 1.5: return "EXTREMO"
        elif ratio_corto > 1.3: return "EXPANSION"
        return "NORMAL"
    
    def _abrir_contrato(self, señal: BinarySeñal, precio_entrada: float) -> BinaryOperacion:
        """Abre un nuevo contrato binario."""
        op = BinaryOperacion(
            id_operacion=f"BIN_{señal.tiempo.strftime('%Y%m%d_%H%M%S')}_{len(self.operaciones_cerradas)}",
            señal=señal,
            simbolo=señal.simbolo,
            direccion=señal.direccion,
            precio_entrada=precio_entrada,
            timestamp_entrada=señal.tiempo,
            expiry_timestamp=señal.expiry_timestamp,
            expiry_minutes=señal.expiry_minutes,
            payout_pct=señal.payout_pct,
            contract_amount=señal.contract_amount,
            contract_count=señal.contract_count,
        )
        self.operaciones_abiertas.append(op)
        return op
    
    def _cerrar_contrato(self, operacion: BinaryOperacion, precio_expiry: float, timestamp_expiry: datetime):
        """Cierra contrato al expiry y calcula PnL."""
        # Determinar resultado
        if operacion.direccion == 1:  # CALL
            win = precio_expiry > operacion.precio_entrada
        else:  # PUT
            win = precio_expiry < operacion.precio_entrada
        
        # En caso de precio igual (raro), considerar LOSS para la casa
        if precio_expiry == operacion.precio_entrada:
            win = False
        
        # PnL
        if win:
            pnl = operacion.contract_amount * operacion.contract_count * operacion.payout_pct
        else:
            pnl = -operacion.contract_amount * operacion.contract_count
        
        operacion.precio_expiry = precio_expiry
        operacion.timestamp_expiry = timestamp_expiry
        operacion.resultado = "WIN" if win else "LOSS"
        operacion.pnl_dinero = pnl
        operacion.pnl_pct = (pnl / (operacion.contract_amount * operacion.contract_count)) * 100
        
        # Mover a cerradas
        self.operaciones_abiertas.remove(operacion)
        self.operaciones_cerradas.append(operacion)
        
        # Actualizar capital y risk manager
        self.capital_actual += pnl
        self.risk_manager.update_capital(self.capital_actual)
        self.risk_manager.record_trade(pnl, operacion.contract_amount, win, timestamp_expiry.date())
        
        # Persistir en DB si disponible
        if self.db is not None:
            try:
                import asyncio
                asyncio.run(self.db.guardar_resultado_operacion({
                    "timestamp_entrada": operacion.timestamp_entrada.isoformat(),
                    "timestamp_salida": operacion.timestamp_expiry.isoformat(),
                    "simbolo": operacion.simbolo,
                    "direccion": operacion.direccion,
                    "detectores_activos": operacion.señal.contexto.get("detectores", []),
                    "pnl_dinero": operacion.pnl_dinero,
                    "razon_salida": operacion.resultado,
                    "fue_ganadora": win,
                    "contract_amount": operacion.contract_amount,
                    "payout_pct": operacion.payout_pct,
                    "expiry_minutes": operacion.expiry_minutes,
                }))
            except Exception as e:
                logger.error(f"Error persistiendo operación binaria: {e}")
    
    def _gestionar_expiraciones(self, bar: Dict[str, Any]):
        """Revisa y cierra contratos que expiran en esta barra."""
        bar_time = bar["timestamp"]
        bar_close = bar["close"]
        
        # Iterar copia para modificar lista original
        for operacion in self.operaciones_abiertas[:]:
            if bar_time >= operacion.expiry_timestamp:
                # El contrato expira en o antes de esta barra
                # Usar close de la barra de expiración (o la actual si ya pasó)
                self._cerrar_contrato(operacion, bar_close, bar_time)
    
    def _calcular_metricas(self) -> BinaryResultado:
        """Calcula métricas finales del backtest binario."""
        resultado = BinaryResultado(
            estrategia=self.estrategia.nombre,
            simbolo=self.activo.simbolo,
            periodo_inicio=self.equity_curve[0][0] if self.equity_curve else datetime(1970, 1, 1),
            periodo_fin=self.equity_curve[-1][0] if self.equity_curve else datetime(1970, 1, 1),
            timeframe_principal="M15",
            capital_inicial=self.capital_inicial,
            capital_final=self.capital_actual,
            operaciones=self.operaciones_cerradas,
            equity_curve=self.equity_curve,
        )
        
        if not self.operaciones_cerradas:
            return resultado
        
        # Métricas básicas
        wins = [op for op in self.operaciones_cerradas if op.resultado == "WIN"]
        losses = [op for op in self.operaciones_cerradas if op.resultado == "LOSS"]
        
        resultado.total_contratos = len(self.operaciones_cerradas)
        resultado.contratos_ganadores = len(wins)
        resultado.contratos_perdedores = len(losses)
        resultado.winrate = (len(wins) / resultado.total_contratos) * 100 if resultado.total_contratos > 0 else 0
        
        # Profit Factor
        total_ganado = sum(op.pnl_dinero for op in wins)
        total_perdido = abs(sum(op.pnl_dinero for op in losses))
        resultado.total_ganado = total_ganado
        resultado.total_perdido = total_perdido
        resultado.total_invertido = sum(op.contract_amount * op.contract_count for op in self.operaciones_cerradas)
        
        if total_perdido > 0:
            resultado.profit_factor = total_ganado / total_perdido
        elif total_ganado > 0:
            resultado.profit_factor = float('inf')
        
        # ROI
        resultado.roi_pct = (total_ganado - total_perdido) / resultado.total_invertido * 100 if resultado.total_invertido > 0 else 0
        resultado.retorno_total_pct = ((self.capital_actual - self.capital_inicial) / self.capital_inicial) * 100
        
        # Payout promedio
        resultado.payout_promedio = np.mean([op.payout_pct for op in self.operaciones_cerradas]) if self.operaciones_cerradas else 0
        
        # Drawdown
        if len(self.equity_curve) > 1:
            equity_values = [e[1] for e in self.equity_curve]
            peak = equity_values[0]
            drawdowns = []
            for value in equity_values:
                if value > peak:
                    peak = value
                dd = (peak - value) / peak * 100 if peak > 0 else 0
                drawdowns.append(dd)
            resultado.max_drawdown_pct = max(drawdowns)
            resultado.max_drawdown_abs = max(drawdowns) * self.capital_inicial / 100 if self.capital_inicial > 0 else 0
        
        # Rachas
        current_streak = 0
        max_win = 0
        max_loss = 0
        last = None
        for op in self.operaciones_cerradas:
            if op.resultado == "WIN":
                if last == "WIN":
                    current_streak += 1
                else:
                    current_streak = 1
                last = "WIN"
                max_win = max(max_win, current_streak)
            else:
                if last == "LOSS":
                    current_streak += 1
                else:
                    current_streak = 1
                last = "LOSS"
                max_loss = max(max_loss, current_streak)
        resultado.racha_ganadora_max = max_win
        resultado.racha_perdedora_max = max_loss
        
        # Sharpe / Sortino (simplificado sobre equity curve)
        if len(self.equity_curve) > 1:
            returns = []
            for i in range(1, len(self.equity_curve)):
                prev = self.equity_curve[i-1][1]
                curr = self.equity_curve[i][1]
                if prev > 0:
                    returns.append((curr - prev) / prev)
            if returns and np.std(returns) > 0:
                resultado.sharpe_ratio = (np.mean(returns) / np.std(returns)) * np.sqrt(252)
                downside = [r for r in returns if r < 0]
                if downside and np.std(downside) > 0:
                    resultado.sortino_ratio = (np.mean(returns) / np.std(downside)) * np.sqrt(252)
        
        return resultado
    
    def ejecutar(
        self,
        feeds: Dict[str, CSVFeed],
        params_estrategia: Optional[Dict[str, Any]] = None,
    ) -> BinaryResultado:
        """
        Ejecuta el backtest binario completo.
        
        Args:
            feeds: Dict {timeframe: CSVFeed} con datos
            params_estrategia: Parámetros para la estrategia
        
        Returns:
            BinaryResultado con métricas completas
        """
        # Reset estado
        self.capital_actual = self.capital_inicial
        self.operaciones_abiertas = []
        self.operaciones_cerradas = []
        self.equity_curve = []
        self.señales_generadas = []
        self._col_arrays = None
        self._ema_arrays = None
        self._precalc = None
        self._precalc_emas = None
        self.risk_manager = BinaryRiskManager(self.risk_manager.config, self.capital_inicial)
        
        # Setup estrategia
        self.estrategia.setup(params_estrategia or {}, self.activo)
        
        # Feed de referencia (M15)
        ref_timeframe = min(feeds.keys(), key=lambda tf: CSVFeed.TIMEFRAME_MAP.get(tf, 999999))
        ref_feed = feeds[ref_timeframe]
        
        # Precalcular H1/H4/D1 UNA vez
        from kernel.feeds.csv_resample import resamplear_ohlc
        df_full = ref_feed.df
        self._precalc: Dict[str, Optional[pd.DataFrame]] = {}
        for tf in ["H1", "H4", "D1"]:
            if tf == ref_timeframe: continue
            try:
                self._precalc[tf] = resamplear_ohlc(df_full, tf)
            except Exception as e:
                logger.warning(f"No se pudo precalcular {tf}: {e}")
                self._precalc[tf] = None
        
        # Precalcular EMAs
        self._precalc_emas: Dict[str, Dict[str, pd.Series]] = {}
        for tf in ["H1", "H4", "D1"]:
            df_tf = self._precalc.get(tf)
            if df_tf is None or df_tf.empty: continue
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
            # 1. Gestionar expiraciones de contratos abiertos
            self._gestionar_expiraciones(bar)
            
            # 2. Construir contexto
            self.contexto = self._crear_contexto(feeds, bar=bar, pos=ref_feed.idx)
            self.contexto.precio = bar["close"]
            self.contexto.tiempo = bar["timestamp"]
            
            # 3. Ejecutar estrategia
            señales = self.estrategia.detectar(self.contexto)
            
            # 4. Procesar señales (convertir a BinarySeñal si necesario)
            for señal in señales:
                if not isinstance(señal, BinarySeñal):
                    # Convertir Señal estándar a BinarySeñal
                    señal = BinarySeñal(
                        estrategia=señal.estrategia,
                        simbolo=señal.simbolo,
                        direccion=señal.direccion,
                        precio=señal.precio,
                        tiempo=señal.tiempo,
                        etiqueta=señal.etiqueta,
                        confianza=señal.confianza,
                        score=señal.score,
                        narrativa=señal.narrativa,
                        contexto=señal.contexto,
                        overlays=señal.overlays,
                    )
                
                # Completar campos binarios si faltan
                if señal.expiry_timestamp is None and señal.tiempo:
                    señal.expiry_timestamp = señal.tiempo + timedelta(minutes=señal.expiry_minutes)
                
                # Obtener payout del activo
                señal.payout_pct = self.activo.get_payout(señal.expiry_minutes)
                
                # Calcular tamaño según risk manager
                contract_amount = self.risk_manager.calculate_next_amount(
                    payout=señal.payout_pct,
                    winrate_estimate=señal.confianza[0] / 100 if isinstance(señal.confianza, tuple) else 0.55
                )
                
                if contract_amount <= 0 or not self.risk_manager.can_trade():
                    continue
                
                señal.contract_amount = contract_amount
                señal.contract_count = 1  # Por ahora 1 contrato por señal
                
                # Abrir contrato
                precio_entrada = bar["close"]  # Entrada al close de la barra de señal
                self._abrir_contrato(señal, precio_entrada)
                self.señales_generadas.append(señal)
            
            # 5. Registrar equity (capital + PnL flotante de contratos abiertos)
            equity_flotante = 0.0
            for op in self.operaciones_abiertas:
                # PnL no realizado (aproximado con close actual)
                # En binarias no hay PnL flotante real hasta expiry, 
                # pero podemos estimar valor esperado
                if op.direccion == 1:
                    prob_win = 0.5  # Simplificado
                    ev = prob_win * op.contract_amount * op.payout_pct - (1-prob_win) * op.contract_amount
                else:
                    prob_win = 0.5
                    ev = prob_win * op.contract_amount * op.payout_pct - (1-prob_win) * op.contract_amount
                equity_flotante += ev * op.contract_count
            
            equity_total = self.capital_actual + equity_flotante
            self.equity_curve.append((bar["timestamp"], equity_total))
        
        # Cerrar contratos que queden abiertos al final (usar último precio)
        last_bar = {"timestamp": ref_feed.df.index[-1], "close": ref_feed.df["close"].iloc[-1]}
        for operacion in self.operaciones_abiertas[:]:
            self._cerrar_contrato(operacion, last_bar["close"], last_bar["timestamp"])
        
        # Calcular métricas finales
        return self._calcular_metricas()


def run_binary_backtest(
    estrategia: Estrategia,
    activo: BinaryActivoInfo,
    data_path: str,
    timeframe: str = "M15",
    params: Optional[Dict[str, Any]] = None,
    capital: float = 10000.0,
    risk_config: Optional[BinaryRiskConfig] = None,
) -> BinaryResultado:
    """
    Helper para ejecutar backtest binario rápidamente.
    """
    feed = CSVFeed(path=data_path, timeframe=timeframe, symbol=activo.simbolo)
    
    engine = BinaryBacktestEngine(
        estrategia=estrategia,
        activo=activo,
        capital_inicial=capital,
        risk_config=risk_config,
    )
    
    return engine.ejecutar(feeds={timeframe: feed}, params_estrategia=params)