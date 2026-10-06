#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PivotRadar Hybrid v8.0 — Motor Orquestador
Arquitectura plugin: detectores independientes + scoring cruzado + narrativa + persistencia.
Lógica de detección idéntica a v7.9. Solo cambia la estructura interna.
"""
import logging
import math
import os
import time
import hashlib
import threading
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Tuple, Optional, Set

logger = logging.getLogger(__name__)

from core.estructuras import EstructuraRef, Signal, DetectorLatch, MSSCache, ZonaCache
from core import (
    Contexto, Detector,
    EstructuraProvider,
    DetectorD1, DetectorD2, DetectorD2Anticipacion,
    DetectorD3, DetectorD4, DetectorD5,
)
from core.scoring import ScoringEngine
from core.hipotesis import generar_hipotesis
from core.alertas import AlertasEngine
# Migración G12: usar kernel.storage en lugar de core.persistencia
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kernel.storage import Database


ATR_BUFFER_SIZE = 55
MAX_PENDING_SIGNALS = 500


class PivotRadarEngine:
    _LATCH_IDX_MAP = {"D1": 0, "D2": 1, "D2_ANTICIPACION": 6, "D3": 2, "D3_DEF": 3, "D4": 4, "D5": 5}

    def __init__(
        self,
        symbol: str = "EURUSD",
        ntfy_topic: str = "",
        ntfy_server: str = "https://ntfy.sh",
        timer_sec: int = 1,
        modo_test: bool = False,
        n_ruptura: int = 4,
        d1_atr_threshold: float = 0.50,
        body_ratio_min: float = 0.40,
        d1_use_retest: bool = True,
        d1_use_volume: bool = True,
        d1_min_volume: float = 1.2,
        sweep_n: int = 6,
        sweep_wick_min: float = 0.55,
        reclaim_body_min: float = 0.55,
        equal_hl_window: int = 10,
        equal_hl_tol: float = 0.15,
        d2_anticipar: bool = True,
        fvg_min_size_atr: float = 0.20,
        fvg_body_ratio: float = 0.55,
        fvg_mitig_umbral: float = 0.50,
        ob_lookback: int = 12,
        ob_body_min: float = 0.40,
        ob_impulse_min: float = 0.70,
        mss_lookback_h4: int = 20,
        mss_max_age_h4_bars: int = 12,
        pivot_depth: int = 2,
        pivot_lookback: int = 24,
        sweep_distancia: float = 1.5,
        zona_margen: float = 0.5,
        peso_estructural: float = 0.25,
        cola_senales_file: str = "Cola_Senales_v78.csv",
        lock_timeout_ms: int = 5000,
        lock_stale_sec: int = 5,
        cola_d1_enabled: bool = True,
        cola_d2_enabled: bool = True,
        cola_d3_enabled: bool = True,
        cola_d4_enabled: bool = True,
        cola_d5_enabled: bool = True,
        data_dir: str = "./pivotradar_data",
        point: float = 0.00001,
        broker_tz_offset_hours: int = 2,
    ):
        self.symbol = symbol
        self.point = point
        self.timer_sec = timer_sec
        self.modo_test = modo_test
        self.data_dir = data_dir
        self.broker_tz_offset = timezone(timedelta(hours=broker_tz_offset_hours))

        # Parámetros en atributos para compatibilidad con setattr desde manifiesto
        self.inp_n_ruptura = n_ruptura
        self.inp_d1_atr_threshold = d1_atr_threshold
        self.inp_body_ratio_min = body_ratio_min
        self.inp_d1_use_retest = d1_use_retest
        self.inp_d1_use_volume = d1_use_volume
        self.inp_d1_min_volume = d1_min_volume
        self.inp_sweep_n = sweep_n
        self.inp_sweep_wick_min = sweep_wick_min
        self.inp_reclaim_body_min = reclaim_body_min
        self.inp_equal_hl_window = equal_hl_window
        self.inp_equal_hl_tol = equal_hl_tol
        self.inp_d2_anticipar = d2_anticipar
        self.inp_fvg_min_size_atr = fvg_min_size_atr
        self.inp_fvg_body_ratio = fvg_body_ratio
        self.inp_fvg_mitig_umbral = fvg_mitig_umbral
        self.inp_ob_lookback = ob_lookback
        self.inp_ob_body_min = ob_body_min
        self.inp_ob_impulse_min = ob_impulse_min
        self.inp_mss_lookback_h4 = mss_lookback_h4
        self.inp_mss_max_age_h4_bars = mss_max_age_h4_bars
        self.inp_pivot_depth = pivot_depth
        self.inp_pivot_lookback = pivot_lookback
        self.inp_sweep_distancia = sweep_distancia
        self.inp_zona_margen = zona_margen
        self.inp_peso_estructural = peso_estructural
        self.inp_cola_senales_file = cola_senales_file
        self.inp_lock_timeout_ms = lock_timeout_ms
        self.inp_lock_stale_sec = lock_stale_sec
        self.inp_cola_d1_enabled = cola_d1_enabled
        self.inp_cola_d2_enabled = cola_d2_enabled
        self.inp_cola_d3_enabled = cola_d3_enabled
        self.inp_cola_d4_enabled = cola_d4_enabled
        self.inp_cola_d5_enabled = cola_d5_enabled

        os.makedirs(self.data_dir, exist_ok=True)

        # Estado
        self.g_last_bar_time = self._epoch()
        self.g_pending_signals: List[Signal] = []
        self.g_pending_ids: Set[int] = set()
        self.g_copybuffer_fail_count = 0
        self.g_last_volume_calc_time = self._epoch()
        self.g_cached_volume_ratio = 1.0
        self.g_cached_volume_bar_shift = -1
        self.g_cached_volume_lookback = -1
        self.g_atr14_history = [0.0] * 20
        self.g_is_processing = False
        self.g_lock = threading.Lock()
        self.g_detector_latch = [DetectorLatch() for _ in range(7)]
        self.g_g1 = 0.0; self.g_g2 = 0.0; self.g_g3 = 0.0; self.g_g4 = 0.0
        self.g_estructura = EstructuraRef()
        self.g_last_struct_update = self._epoch()
        self.g_mss_cache = MSSCache()
        self.g_zona_cache = ZonaCache()
        self.g_last_g_calc_bar = self._epoch()

        # DataFrames
        self.df_m15 = self.df_h1 = self.df_h4 = self.df_d1 = None

        # Buffers
        self.g_atr8_buffer = []
        self.g_atr14_buffer = []
        self.g_atr30_buffer = []
        self.g_ema21_buffer = []
        self.g_ema50_buffer = []
        self.g_rsi14_buffer = []
        self.g_ema50_d1_buffer = []
        self.g_ema200_d1_buffer = []
        self.g_ema20_h4_buffer = []
        self.g_ema50_h4_buffer = []

        # Subsistemas - Migración G12: usar Database en lugar de Persistencia CSV
        self.db = Database(os.path.join(data_dir, "pivot_core.db"))
        self.db.initialize()
        self.alertas = AlertasEngine(ntfy_topic, ntfy_server, symbol, point)
        self.scoring = None  # se crea por vela

        # Detectores
        self.detectores: List[Detector] = [
            DetectorD1(),
            DetectorD2(),
            DetectorD2Anticipacion(),
            DetectorD3(),
            DetectorD4(),
            DetectorD5(),
        ]

        # Cargar pending desde SQLite en lugar de CSV - Migración G12
        # cargar_cola_pendientes retorna (dict signal_id->fila, set de ids)
        import asyncio
        loop = asyncio.new_event_loop()
        pending_map, pending_ids = loop.run_until_complete(self.db.cargar_cola_pendientes())
        loop.close()

        self.g_pending_signals = []
        self.g_pending_ids = set()
        rows = pending_map.values() if isinstance(pending_map, dict) else pending_map
        for p in rows:
            try:
                raw_id = p.get('signal_id')
                sid = int(raw_id) if raw_id not in (None, '') else 0
                sig = Signal()
                sig.id = sid
                sig.symbol = p.get('symbol', self.symbol)
                sig.detector = p.get('detector', '')
                entry_raw = p.get('entry_time') or p.get('created_at')
                if entry_raw:
                    try:
                        et = datetime.fromisoformat(str(entry_raw))
                    except ValueError:
                        et = None
                else:
                    et = None
                if et is None or et.tzinfo is None:
                    et = (et or datetime(1970, 1, 1)).replace(tzinfo=timezone.utc)
                sig.entry_time = et
                sig.csv_written = True
                self.g_pending_signals.append(sig)
                self.g_pending_ids.add(sid)
            except Exception as e:
                logger.error(f"Error restaurando señal pendiente {p}: {e}")

        print("=== PivotRadar Hybrid v8.0 Python ===")
        print(f"Símbolo: {self.symbol} | Timeframe: M15")
        print(f"Broker TZ offset: UTC{'+' if broker_tz_offset_hours >= 0 else ''}{broker_tz_offset_hours}")
        print("TODOS LOS DETECTORES INTRAVELA")
        print("ARQUITECTURA PLUGIN: D0-D5 desacoplados")
        print("=====================================")

        if self.modo_test:
            self.test_ntfy()

    # =========================================================================
    # INDICADORES
    # =========================================================================
    @staticmethod
    def _ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def _atr(df: pd.DataFrame, period: int) -> pd.Series:
        high = df["high"]; low = df["low"]; close = df["close"]
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.ewm(alpha=1.0 / period, adjust=False).mean()

    @staticmethod
    def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _update_indicators(self) -> bool:
        if self.df_m15 is None or len(self.df_m15) < 55:
            return False
        df = self.df_m15.copy()
        self.g_atr8_buffer = self._atr(df, 8).iloc[-ATR_BUFFER_SIZE:].tolist()[::-1]
        self.g_atr14_buffer = self._atr(df, 14).iloc[-ATR_BUFFER_SIZE:].tolist()[::-1]
        self.g_atr30_buffer = self._atr(df, 30).iloc[-ATR_BUFFER_SIZE:].tolist()[::-1]
        self.g_ema21_buffer = self._ema(df["close"], 21).iloc[-ATR_BUFFER_SIZE:].tolist()[::-1]
        self.g_ema50_buffer = self._ema(df["close"], 50).iloc[-ATR_BUFFER_SIZE:].tolist()[::-1]
        self.g_rsi14_buffer = self._rsi(df["close"], 14).iloc[-ATR_BUFFER_SIZE:].tolist()[::-1]

        if self.df_d1 is not None and len(self.df_d1) >= 205:
            self.g_ema50_d1_buffer = self._ema(self.df_d1["close"], 50).iloc[-5:].tolist()[::-1]
            self.g_ema200_d1_buffer = self._ema(self.df_d1["close"], 200).iloc[-5:].tolist()[::-1]
        else:
            self.g_ema50_d1_buffer = []
            self.g_ema200_d1_buffer = []

        if self.df_h4 is not None and len(self.df_h4) >= 20:
            self.g_ema20_h4_buffer = self._ema(self.df_h4["close"], 20).iloc[-20:].tolist()[::-1]
            self.g_ema50_h4_buffer = self._ema(self.df_h4["close"], 50).iloc[-20:].tolist()[::-1]
        else:
            self.g_ema20_h4_buffer = []
            self.g_ema50_h4_buffer = []
        return True

    # =========================================================================
    # GETTERS DE CONTEXTO
    # =========================================================================
    def get_trend_d1(self) -> str:
        if len(self.g_ema50_d1_buffer) < 2 or len(self.g_ema200_d1_buffer) < 2:
            return "NEUTRO"
        ema50 = self.g_ema50_d1_buffer[1]
        ema200 = self.g_ema200_d1_buffer[1]
        if ema50 == 0 or ema200 == 0:
            return "NEUTRO"
        eps = ema200 * 0.0005
        if ema50 > ema200 + eps: return "ALCISTA"
        if ema50 < ema200 - eps: return "BAJISTA"
        return "NEUTRO"

    def get_volume_ratio(self, bar_shift: int, n_lookback: int) -> float:
        if self.df_m15 is None:
            return 1.0
        vol_signal = self._i_volume(self.df_m15, bar_shift)
        if vol_signal <= 0:
            return 1.0
        sum_prev = 0; count = 0
        for i in range(1, n_lookback + 1):
            vol = self._i_volume(self.df_m15, bar_shift + i)
            if vol > 0:
                sum_prev += vol; count += 1
        if count == 0 or sum_prev <= 0:
            return 1.0
        return vol_signal / (sum_prev / count)

    def get_volume_ratio_cached(self, bar_shift: int, n_lookback: int) -> float:
        bar_time = self._i_time(self.df_m15, bar_shift)
        valid = (
            self.g_last_volume_calc_time == bar_time
            and self.g_cached_volume_bar_shift == bar_shift
            and self.g_cached_volume_lookback == n_lookback
        )
        if bar_shift == 0 and valid:
            now = datetime.now(timezone.utc)
            if self.g_last_volume_calc_time is not None and (now - self.g_last_volume_calc_time).total_seconds() > 1:
                valid = False
        if valid:
            return self.g_cached_volume_ratio
        result = self.get_volume_ratio(bar_shift, n_lookback)
        self.g_cached_volume_ratio = result
        self.g_cached_volume_bar_shift = bar_shift
        self.g_cached_volume_lookback = n_lookback
        self.g_last_volume_calc_time = bar_time
        return result

    def _to_broker_time(self, bar_time: datetime) -> datetime:
        if bar_time is None or bar_time.year < 2000:
            return bar_time
        if bar_time.tzinfo is None:
            bar_time = bar_time.replace(tzinfo=timezone.utc)
        return bar_time.astimezone(self.broker_tz_offset)

    def get_session(self, bar_time: datetime) -> str:
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

    def get_kill_zone(self, bar_time: datetime) -> str:
        if bar_time is None or bar_time.year < 2000:
            return "NONE"
        bt = self._to_broker_time(bar_time)
        hour = bt.hour; minute = bt.minute
        if hour == 7 or hour == 8:
            return "LONDON_OPEN_KILL"
        if hour == 13 or (hour == 14 and minute <= 30):
            return "NY_OPEN_KILL"
        if 13 <= hour < 15:
            return "LONDON_NY_OVERLAP"
        return "NONE"

    def get_trend_velas(self) -> int:
        if len(self.g_ema21_buffer) < 2 or len(self.g_ema50_buffer) < 2:
            return 0
        up = self.g_ema21_buffer[1] > self.g_ema50_buffer[1]
        down = self.g_ema21_buffer[1] < self.g_ema50_buffer[1]
        if not up and not down:
            return 0
        count = 0
        max_i = min(ATR_BUFFER_SIZE, len(self.g_ema21_buffer), len(self.g_ema50_buffer))
        for i in range(1, max_i):
            u = self.g_ema21_buffer[i] > self.g_ema50_buffer[i]
            d = self.g_ema21_buffer[i] < self.g_ema50_buffer[i]
            if not u and not d:
                continue
            if up and not u: break
            if down and not d: break
            count += 1
        return count

    def is_volatility_expanding(self) -> bool:
        if self.g_atr14_history[10] == 0:
            return False
        avg = sum(self.g_atr14_history[1:11]) / 10.0
        return self.g_atr14_history[0] > avg * 1.30

    def is_volatility_compressing(self) -> bool:
        if self.g_atr14_history[10] == 0:
            return False
        avg = sum(self.g_atr14_history[1:11]) / 10.0
        return self.g_atr14_history[0] < avg * 0.80

    def update_atr_history(self):
        for i in range(19, 0, -1):
            self.g_atr14_history[i] = self.g_atr14_history[i - 1]
        self.g_atr14_history[0] = self.g_atr14_buffer[0] if self.g_atr14_buffer else 0.0

    # =========================================================================
    # HELPERS DE SERIES
    # =========================================================================
    def _i_high(self, df: pd.DataFrame, shift: int) -> float:
        if df is None or shift < 0 or shift >= len(df):
            return 0.0
        return float(df.iloc[-(shift + 1)]["high"])

    def _i_low(self, df: pd.DataFrame, shift: int) -> float:
        if df is None or shift < 0 or shift >= len(df):
            return 0.0
        return float(df.iloc[-(shift + 1)]["low"])

    def _i_close(self, df: pd.DataFrame, shift: int) -> float:
        if df is None or shift < 0 or shift >= len(df):
            return 0.0
        return float(df.iloc[-(shift + 1)]["close"])

    def _i_open(self, df: pd.DataFrame, shift: int) -> float:
        if df is None or shift < 0 or shift >= len(df):
            return 0.0
        return float(df.iloc[-(shift + 1)]["open"])

    def _i_volume(self, df: pd.DataFrame, shift: int) -> int:
        if df is None or shift < 0 or shift >= len(df):
            return 0
        row = df.iloc[-(shift + 1)]
        col = "tick_volume" if "tick_volume" in df.columns else "volume"
        return int(row[col])

    @staticmethod
    def _epoch() -> datetime:
        """Epoch timezone-aware, coherente con índices datetime64[UTC]."""
        return datetime(1970, 1, 1, tzinfo=timezone.utc)

    def _i_time(self, df: pd.DataFrame, shift: int) -> datetime:
        if df is None or shift < 0 or shift >= len(df):
            return self._epoch()
        t = df.index[-(shift + 1)]
        if isinstance(t, pd.Timestamp):
            return t.to_pydatetime()
        return t

    def _i_bar_shift(self, df: pd.DataFrame, target_time: datetime, exact: bool = True) -> int:
        if df is None:
            return -1
        idx = df.index
        if target_time is not None and isinstance(idx, pd.DatetimeIndex) and getattr(idx.dtype, "tz", None) is not None and getattr(target_time, "tzinfo", None) is None:
            target_time = target_time.replace(tzinfo=idx.dtype.tz)
        if exact:
            matches = idx[idx == target_time]
            if len(matches) > 0:
                return len(idx) - idx.get_loc(matches[0]) - 1
            return -1
        else:
            mask = idx <= target_time
            if not mask.any():
                return -1
            pos = mask.nonzero()[0][-1]
            return len(idx) - pos - 1

    # =========================================================================
    # DEDUPLICACIÓN
    # =========================================================================
    @staticmethod
    def build_signal_id(bar_time: datetime, detector: str, direction: int, key_level: float) -> int:
        if bar_time is None or bar_time.year < 2000:
            bar_time = datetime(1970, 1, 1, tzinfo=timezone.utc)
        ts = int(bar_time.timestamp())
        raw = f"{ts}|{detector}|{direction}|{key_level:.10f}"
        # Máscara para mantener el id dentro del rango signed de SQLite INTEGER
        return int(hashlib.md5(raw.encode()).hexdigest()[:16], 16) & 0x7FFFFFFFFFFFFFFF

    def is_duplicate_signal(self, sid: int) -> bool:
        return sid in self.g_pending_ids

    def has_detector_fired_this_bar(self, detector: str, direction: int, key_level: float) -> bool:
        idx = self._LATCH_IDX_MAP.get(detector, -1)
        if idx < 0:
            return False
        current_bar = self._i_time(self.df_m15, 0)
        from core.utils import build_pattern_key
        pattern_key = build_pattern_key(detector, direction, key_level)
        latch = self.g_detector_latch[idx]
        if latch.last_signal_bar != current_bar:
            latch.has_fired_this_bar = False
            latch.last_pattern_key = ""
        if latch.has_fired_this_bar and latch.last_pattern_key == pattern_key:
            return True
        return False

    def mark_detector_fired(self, detector: str, direction: int, key_level: float):
        idx = self._LATCH_IDX_MAP.get(detector, -1)
        if idx < 0:
            return
        current_bar = self._i_time(self.df_m15, 0)
        from core.utils import build_pattern_key
        latch = self.g_detector_latch[idx]
        latch.last_signal_bar = current_bar
        latch.last_pattern_key = build_pattern_key(detector, direction, key_level)
        latch.has_fired_this_bar = True

    # =========================================================================
    # MSS H4
    # =========================================================================
    def detect_mss_h4(self) -> Tuple[bool, int, str, float]:
        if self.df_h4 is None or len(self.df_h4) < 50:
            return False, 0, "", 0.0
        current_h4_bar = self.df_h4.index[-1]
        if isinstance(current_h4_bar, pd.Timestamp):
            current_h4_bar = current_h4_bar.to_pydatetime()
        if self.g_mss_cache.valid and self.g_mss_cache.calc_time == current_h4_bar:
            return True, self.g_mss_cache.bars_ago, self.g_mss_cache.dir, self.g_mss_cache.level

        max_scan = min(self.inp_mss_max_age_h4_bars, len(self.df_h4) - 3)
        for i in range(1, max_scan + 1):
            close_i = float(self.df_h4.iloc[-(i + 1)]["close"])
            if close_i == 0:
                continue
            prior_high = 0.0
            prior_low = 999999.0
            window_start = i + 1
            window_end = min(i + 1 + self.inp_mss_lookback_h4, len(self.df_h4))
            for k in range(window_start, window_end):
                hk = float(self.df_h4.iloc[-(k + 1)]["high"])
                lk = float(self.df_h4.iloc[-(k + 1)]["low"])
                if hk == 0 or lk == 0:
                    continue
                if hk > prior_high:
                    prior_high = hk
                if lk < prior_low:
                    prior_low = lk
            if prior_high == 0 or prior_low >= 999999.0:
                continue
            if close_i > prior_high:
                self.g_mss_cache.valid = True
                self.g_mss_cache.calc_time = current_h4_bar
                self.g_mss_cache.bars_ago = i
                self.g_mss_cache.dir = "ALCISTA"
                self.g_mss_cache.level = prior_high
                return True, i, "ALCISTA", prior_high
            if close_i < prior_low:
                self.g_mss_cache.valid = True
                self.g_mss_cache.calc_time = current_h4_bar
                self.g_mss_cache.bars_ago = i
                self.g_mss_cache.dir = "BAJISTA"
                self.g_mss_cache.level = prior_low
                return True, i, "BAJISTA", prior_low
        self.g_mss_cache.valid = False
        return False, 0, "", 0.0

    # =========================================================================
    # ZONA PREMIUM/DISCOUNT
    # =========================================================================
    def es_zona_premium_discount(self, nivel: float) -> Tuple[bool, str]:
        current_bar = self._i_time(self.df_m15, 0)
        if self.g_zona_cache.valid and self.g_zona_cache.calc_time == current_bar:
            zona = "PREMIUM" if nivel > self.g_zona_cache.mid else "DISCOUNT"
            return True, zona
        max_high = 0.0; min_low = 999999.0
        for i in range(1, 51):
            h = self._i_high(self.df_m15, i)
            l = self._i_low(self.df_m15, i)
            if h == 0 or l == 0:
                break
            if h > max_high: max_high = h
            if l < min_low: min_low = l
        if max_high > 0 and min_low > 0 and max_high > min_low:
            mid = (max_high + min_low) / 2.0
            self.g_zona_cache.valid = True
            self.g_zona_cache.calc_time = current_bar
            self.g_zona_cache.mid = mid
            zona = "PREMIUM" if nivel > mid else "DISCOUNT"
            return True, zona
        return False, "NEUTRO"

    # =========================================================================
    # EVALUAR CONTEXTO ESTRUCTURAL
    # =========================================================================
    def evaluar_contexto_estructural(self, direction: int, nivel: float, detector: str, trend_d1: str) -> Tuple[float, float]:
        score = 0.0; distancia = 0.0
        if not self.g_estructura.valida or self.g_estructura.sweep_nivel == 0:
            return 50.0, distancia
        atr14 = self.g_atr14_buffer[0] if self.g_atr14_buffer else 0.0
        if atr14 <= 0:
            return 50.0, distancia
        tolerancia = atr14 * 0.5
        distancia = abs(nivel - self.g_estructura.sweep_nivel) / self.point
        if distancia <= tolerancia / self.point:
            score += 50.0
        elif distancia <= tolerancia * 2 / self.point:
            score += 30.0
        else:
            score += 10.0
        if self.g_estructura.en_zona:
            score += 25.0
        if self.g_estructura.dir_estructura != "NEUTRO":
            if (direction == 1 and self.g_estructura.dir_estructura == "ALCISTA") or (direction == -1 and self.g_estructura.dir_estructura == "BAJISTA"):
                score += 25.0
            else:
                score += 5.0
        else:
            score += 10.0
        from core.utils import clamp_0_100
        return clamp_0_100(score), distancia

    # =========================================================================
    # RÉGIMEN DE VOLATILIDAD
    # =========================================================================
    def clasificar_regimen_volatilidad(self) -> str:
        atr5 = self.g_atr8_buffer[0] if self.g_atr8_buffer else 0.0
        atr14 = self.g_atr14_buffer[0] if self.g_atr14_buffer else 0.0
        atr50 = self.g_atr30_buffer[0] if self.g_atr30_buffer else 0.0
        if atr14 == 0 or atr50 == 0:
            return "NORMAL"
        ratio_corto = atr5 / atr14
        ratio_largo = atr14 / atr50
        if ratio_largo < 0.6 and ratio_corto < 0.8:
            return "COMPRESION"
        elif ratio_largo > 1.5:
            return "EXTREMO"
        elif ratio_corto > 1.3:
            return "EXPANSION"
        return "NORMAL"

    # =========================================================================
    # ENTRY POINT
    # =========================================================================
    def on_data(self, df_m15: pd.DataFrame, df_h1: pd.DataFrame = None,
                df_h4: pd.DataFrame = None, df_d1: pd.DataFrame = None):
        with self.g_lock:
            if self.g_is_processing:
                return
            self.g_is_processing = True
        try:
            self.df_m15 = df_m15.copy() if df_m15 is not None else None
            self.df_h1 = df_h1.copy() if df_h1 is not None else None
            self.df_h4 = df_h4.copy() if df_h4 is not None else None
            self.df_d1 = df_d1.copy() if df_d1 is not None else None
            self.process_intrabar()
            self.alertas.process_alert_queue()
        finally:
            with self.g_lock:
                self.g_is_processing = False

    def process_intrabar(self):
        if not self._update_indicators():
            return
        self.measure_returns()
        self.update_atr_history()

        current_bar = self._i_time(self.df_m15, 0)
        session = self.get_session(current_bar)
        kill_zone = self.get_kill_zone(current_bar)
        vol_exp = self.is_volatility_expanding()
        vol_comp = self.is_volatility_compressing()
        trend_d1 = self.get_trend_d1()
        regimen_vol = self.clasificar_regimen_volatilidad()

        if current_bar != self.g_last_g_calc_bar:
            self.g_g1 = self._calc_g1()
            self.g_g2 = self._calc_g2()
            self.g_g3 = self._calc_g3()
            self.g_g4 = self._calc_g4()
            self.g_last_g_calc_bar = current_bar

        # Actualizar estructura D0
        current_h1_bar = self._i_time(self.df_h1, 0) if self.df_h1 is not None else self._epoch()
        if current_h1_bar != self.g_last_struct_update or self.g_estructura.timestamp.year < 2000:
            ctx_temp = self._build_contexto(session, kill_zone, trend_d1, regimen_vol)
            self.g_estructura = EstructuraProvider(ctx_temp).actualizar()
            self.g_last_struct_update = current_h1_bar

        current_h4_bar = self._i_time(self.df_h4, 0) if self.df_h4 is not None else self._epoch()
        if self.g_mss_cache.calc_time != current_h4_bar:
            self.g_mss_cache.valid = False
        self.g_zona_cache.valid = False

        # Construir Contexto final
        ctx = self._build_contexto(session, kill_zone, trend_d1, regimen_vol)
        ctx.estructura = self.g_estructura
        ctx.mss_cache = self.g_mss_cache
        ctx.zona_cache = self.g_zona_cache
        ctx.g1 = self.g_g1
        ctx.g2 = self.g_g2
        ctx.g3 = self.g_g3
        ctx.g4 = self.g_g4

        # FASE 1: Detección pura
        candidatas = []
        for det in self.detectores:
            # Deduplicación previa
            # Necesitamos saber el key_level antes de detectar; los detectores retornan Signal con entry_time
            sig = det.detectar(ctx)
            if sig is None:
                continue
            # Filtrar señales sin dirección válida (filtros informacionales fallidos)
            if sig.direction == 0:
                continue
            # Determinar key_level para deduplicación
            key_level = sig.nivel_estructural or sig.level_swept or sig.fvg_top or sig.ob_high or sig.entry_price
            sid = self.build_signal_id(sig.entry_time, det.nombre, sig.direction, key_level)
            if self.is_duplicate_signal(sid) or self.has_detector_fired_this_bar(det.nombre, sig.direction, key_level):
                continue
            self.mark_detector_fired(det.nombre, sig.direction, key_level)
            sig.id = sid
            sig.symbol = self.symbol
            sig.session = session
            sig.kill_zone = kill_zone
            sig.trend_d1 = trend_d1
            sig.vol_expanding = vol_exp
            sig.vol_compressing = vol_comp
            sig.atr14 = sig.atr14  # ya en pips
            candidatas.append(sig)

        # FASE 2: Enriquecimiento cruzado (scoring, confluencias)
        self.scoring = ScoringEngine(ctx)
        for sig in candidatas:
            # Calidades según detector
            if sig.detector in ("D2", "D2_ANTICIPACION", "D5"):
                sig.calidad_sweep = self.scoring.calcular_calidad_sweep(
                    sig.sweep_wick_ratio, sig.reclaim_body_ratio,
                    sig.sweep_volume_ratio, sig.sweep_bars_ago, sig.equal_hl_detected
                )
            if sig.detector == "D5":
                sig.calidad_mss = self.scoring.calcular_calidad_mss(
                    sig.sweep_wick_ratio, sig.reclaim_body_ratio, sig.mss_bars_ago_h4
                )
            if sig.detector in ("D3", "D3_DEF"):
                br_impulso = getattr(sig, '_fvg_br', 0.6)
                sig.calidad_fvg = self.scoring.calcular_calidad_fvg(
                    sig.fvg_size_atr, br_impulso, sig.fvg_mitigated
                )
            if sig.detector == "D4":
                ob_vol = getattr(sig, '_ob_volume_ratio', 1.0)
                sig.calidad_ob = self.scoring.calcular_calidad_ob(
                    sig.ob_impulse_atr, sig.ob_bars_ago, ob_vol
                )

            # Salud tendencial
            atr14_real = self.g_atr14_buffer[0] if self.g_atr14_buffer else 1.0
            slope = (self.g_ema21_buffer[0] - self.g_ema21_buffer[3]) / atr14_real if len(self.g_ema21_buffer) > 3 else 0.0
            sig.salud_tendencial = self.scoring.calcular_salud_tendencial(
                self.get_trend_velas(), slope, trend_d1, sig.direction
            )

            # Contexto estructural
            ctx_score, dist = self.evaluar_contexto_estructural(
                sig.direction,
                sig.nivel_estructural or sig.level_swept or sig.fvg_top or sig.ob_high or sig.entry_price,
                sig.detector, trend_d1
            )
            sig.contexto_estructural = ctx_score
            sig.distancia_al_sweep = dist
            sig.en_zona_estructural = self.g_estructura.en_zona

            # Confluencias (solo para detectores que las usan en v7.9)
            if sig.detector in ("D2_ANTICIPACION", "D3", "D3_DEF", "D5"):
                fvg_ahora = any(c.detector in ("D3", "D3_DEF") for c in candidatas)
                fvg_size_max = max((c.fvg_size_atr for c in candidatas if c.detector in ("D3", "D3_DEF")), default=0.0)
                if sig.detector in ("D2_ANTICIPACION", "D3", "D3_DEF"):
                    sig.conf_sweep_fvg = self.scoring.calcular_confluencia_sweep_fvg(
                        self.g_pending_signals, sig.direction, fvg_ahora, fvg_size_max
                    )
                sig.conf_completa = self.scoring.calcular_confluencia_completa(
                    self.g_pending_signals, sig.direction, fvg_ahora, fvg_size_max
                )

        # FASE 3: Hipótesis
        for sig in candidatas:
            generar_hipotesis(sig, ctx, self.g_estructura)
            sig.conviccion = self.scoring.calcular_conviccion(sig)

        # FASE 4: Ruteo
        for sig in candidatas:
            self.route_signal(sig)

    def _build_contexto(self, session, kill_zone, trend_d1, regimen_vol) -> Contexto:
        """Crea un Contexto con todos los parámetros y helpers inyectados."""
        ctx = Contexto(
            df_m15=self.df_m15, df_h1=self.df_h1, df_h4=self.df_h4, df_d1=self.df_d1,
            g_atr8_buffer=self.g_atr8_buffer,
            g_atr14_buffer=self.g_atr14_buffer,
            g_atr30_buffer=self.g_atr30_buffer,
            g_ema21_buffer=self.g_ema21_buffer,
            g_ema50_buffer=self.g_ema50_buffer,
            g_rsi14_buffer=self.g_rsi14_buffer,
            g_ema50_d1_buffer=self.g_ema50_d1_buffer,
            g_ema200_d1_buffer=self.g_ema200_d1_buffer,
            g_ema20_h4_buffer=self.g_ema20_h4_buffer,
            g_ema50_h4_buffer=self.g_ema50_h4_buffer,
            session=session, kill_zone=kill_zone, trend_d1=trend_d1,
            regimen_vol=regimen_vol,
            point=self.point,
            broker_tz_offset=self.broker_tz_offset,
            # Parámetros
            inp_n_ruptura=self.inp_n_ruptura,
            inp_d1_atr_threshold=self.inp_d1_atr_threshold,
            inp_body_ratio_min=self.inp_body_ratio_min,
            inp_d1_use_retest=self.inp_d1_use_retest,
            inp_d1_use_volume=self.inp_d1_use_volume,
            inp_d1_min_volume=self.inp_d1_min_volume,
            inp_sweep_n=self.inp_sweep_n,
            inp_sweep_wick_min=self.inp_sweep_wick_min,
            inp_reclaim_body_min=self.inp_reclaim_body_min,
            inp_equal_hl_window=self.inp_equal_hl_window,
            inp_equal_hl_tol=self.inp_equal_hl_tol,
            inp_d2_anticipar=self.inp_d2_anticipar,
            inp_fvg_min_size_atr=self.inp_fvg_min_size_atr,
            inp_fvg_body_ratio=self.inp_fvg_body_ratio,
            inp_fvg_mitig_umbral=self.inp_fvg_mitig_umbral,
            inp_ob_lookback=self.inp_ob_lookback,
            inp_ob_body_min=self.inp_ob_body_min,
            inp_ob_impulse_min=self.inp_ob_impulse_min,
            inp_mss_lookback_h4=self.inp_mss_lookback_h4,
            inp_mss_max_age_h4_bars=self.inp_mss_max_age_h4_bars,
            inp_pivot_depth=self.inp_pivot_depth,
            inp_pivot_lookback=self.inp_pivot_lookback,
            inp_sweep_distancia=self.inp_sweep_distancia,
            inp_zona_margen=self.inp_zona_margen,
            inp_peso_estructural=self.inp_peso_estructural,
        )
        # Inyectar helpers
        ctx.get_volume_ratio_cached = self.get_volume_ratio_cached
        ctx.get_volume_ratio = self.get_volume_ratio
        ctx.detect_mss_h4 = self.detect_mss_h4
        ctx.es_zona_premium_discount = self.es_zona_premium_discount
        ctx.evaluar_contexto_estructural = self.evaluar_contexto_estructural
        return ctx

    # =========================================================================
    # Métricas G (implementación local para no depender de ScoringEngine con ctx nulo)
    # =========================================================================
    def _calc_g1(self) -> float:
        atr_now = self.g_atr14_buffer[0] if self.g_atr14_buffer else 0.0
        if atr_now <= 0:
            return 50.0
        s = 0.0; count = 0
        for i in range(min(20, len(self.g_atr14_buffer))):
            if self.g_atr14_buffer[i] > 0:
                s += self.g_atr14_buffer[i]; count += 1
        if count == 0:
            return 50.0
        avg = s / count
        if avg <= 0:
            return 50.0
        from core.utils import clamp_0_100
        return clamp_0_100((1.5 - atr_now / avg) / 1.0 * 100.0)

    def _calc_g2(self) -> float:
        up10, down10, up20, down20 = 0, 0, 0, 0
        for i in range(1, 21):
            ci = self._i_close(self.df_m15, i)
            oi = self._i_open(self.df_m15, i)
            up = ci > oi
            if i <= 10:
                if up: up10 += 1
                else: down10 += 1
            if up: up20 += 1
            else: down20 += 1
        d10 = max(up10, down10) / 10.0
        d20 = max(up20, down20) / 20.0
        from core.utils import clamp_0_100
        return clamp_0_100(
            clamp_0_100((d10 - 0.5) / 0.5 * 100.0) * 0.6
            + clamp_0_100((d20 - 0.5) / 0.5 * 100.0) * 0.4
        )

    def _calc_g3(self) -> float:
        n = 10
        ini = self._i_close(self.df_m15, n)
        fin = self._i_close(self.df_m15, 0)
        neto = abs(fin - ini)
        total = 0.0
        for i in range(n):
            h = self._i_high(self.df_m15, i)
            l = self._i_low(self.df_m15, i)
            if h == 0 or l == 0:
                break
            total += h - l
        if total <= 0:
            return 50.0
        from core.utils import clamp_0_100
        return clamp_0_100(neto / total * 100.0)

    def _calc_g4(self) -> float:
        n = 6; m = n // 2
        mp, mu, cp, cu = 0.0, 0.0, 0.0, 0.0
        for i in range(n):
            o = self._i_open(self.df_m15, i)
            c = self._i_close(self.df_m15, i)
            h = self._i_high(self.df_m15, i)
            l = self._i_low(self.df_m15, i)
            if h == 0 or l == 0:
                break
            r = h - l
            if r <= 0:
                continue
            me = r - abs(c - o)
            cu2 = abs(c - o)
            if i < m:
                mu += me; cu += cu2
            else:
                mp += me; cp += cu2
        atr14 = self.g_atr14_buffer[0] if self.g_atr14_buffer else 0.0
        if atr14 <= 0:
            return 0.0
        from core.utils import clamp_0_100
        score_mechas = ((mu - mp) / atr14) * 50.0
        score_cuerpos = ((cu - cp) / atr14) * 50.0
        return clamp_0_100(
            clamp_0_100(score_mechas) + clamp_0_100(score_cuerpos)
        )

    # =========================================================================
    # RUTEAR SEÑAL
    # =========================================================================
    def route_signal(self, sig: Signal):
        from core.utils import clamp_0_100
        sig.calidad_sweep = clamp_0_100(sig.calidad_sweep)
        sig.calidad_mss = clamp_0_100(sig.calidad_mss)
        sig.calidad_fvg = clamp_0_100(sig.calidad_fvg)
        sig.calidad_ob = clamp_0_100(sig.calidad_ob)
        sig.salud_tendencial = clamp_0_100(sig.salud_tendencial)
        sig.contexto_estructural = clamp_0_100(sig.contexto_estructural)

        if len(self.g_pending_signals) >= MAX_PENDING_SIGNALS:
            old = self.g_pending_signals.pop(0)
            self.g_pending_ids.discard(old.id)
        self.g_pending_signals.append(sig)
        self.g_pending_ids.add(sig.id)

        # Migración G12: guardar en SQLite en lugar de CSV
        if not sig.csv_written:
            import asyncio
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self.db.guardar_senal_core(
                signal_id=sig.id,
                entry_time=sig.entry_time,
                symbol=sig.symbol,
                direction=sig.direction,
                entry_price=sig.entry_price,
                detector=sig.detector,
                tipo=sig.tipo or "",
                hipotesis_prob_min=sig.hipotesis_prob_min or 0.0,
                hipotesis_prob_max=sig.hipotesis_prob_max or 0.0,
                hipotesis_expiry_velas=sig.hipotesis_expiry_velas or 0,
                conviccion=sig.conviccion or 0.0,
                regimen_volatilidad=sig.regimen_volatilidad or "",
                fuente="deriv",
            ))
            loop.close()
            sig.csv_written = True

        route = False
        if sig.detector == "D1" and self.inp_cola_d1_enabled: route = True
        if sig.detector == "D2" and self.inp_cola_d2_enabled: route = True
        if sig.detector == "D2_ANTICIPACION" and self.inp_cola_d2_enabled: route = True
        if sig.detector in ("D3", "D3_DEF") and self.inp_cola_d3_enabled: route = True
        if sig.detector == "D4" and self.inp_cola_d4_enabled: route = True
        if sig.detector == "D5" and self.inp_cola_d5_enabled: route = True

        # Migración G12: guardar cola en SQLite en lugar de archivo con lock
        if route:
            import asyncio
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self.db.guardar_cola_senal(
                signal_id=sig.id,
                symbol=sig.symbol,
                detector=sig.detector,
                priority={"D1": 1, "D2": 1, "D2_ANTICIPACION": 2, "D3": 3, "D3_DEF": 3, "D4": 4, "D5": 5}.get(sig.detector, 5)
            ))
            loop.close()

        msg = self.alertas.build_alert_text(sig)
        now = datetime.now(timezone.utc)
        if (now - self.alertas.g_last_ntfy_time).total_seconds() > 5:
            if self.alertas.send_ntfy_message(msg):
                self.alertas.g_last_alert_time = now
                self.alertas.g_last_ntfy_time = now
                print(f"ALERTA: {sig.detector} {sig.symbol} dir={sig.direction}")
            else:
                self.alertas.queue_alert(msg)
                print(f"Alerta encolada: {sig.detector}")
        else:
            self.alertas.queue_alert(msg)
            print(f"Alerta encolada (cooldown): {sig.detector}")

        print(
            f"SEÑAL {sig.detector} [{sig.tipo}] {sig.symbol} "
            f"dir={sig.direction} precio={self.alertas._fmt_price(sig.entry_price)} "
            f"Prob={sig.hipotesis_prob_min}-{sig.hipotesis_prob_max}% "
            f"Conv={sig.conviccion}"
        )

    # =========================================================================
    # MEASURE RETURNS
    # =========================================================================
    def measure_returns(self):
        now = self._i_time(self.df_m15, 0)
        keep = []
        for s in self.g_pending_signals:
            if s.completada:
                continue
            shift = s.entry_bar_shift
            new_shift = self._i_bar_shift(self.df_m15, s.entry_time, exact=False)
            if new_shift >= 0:
                shift = new_shift
                s.entry_bar_shift = new_shift
            else:
                s.completada = True
                continue

            if shift <= 0:
                keep.append(s)
                continue
            if shift > 4:
                s.completada = True
                keep.append(s)
                continue

            # Medicion cerrada: cierre real de la vela h posterior a la entrada.
            # Se espera a que esa vela cierre (shift >= h + 1) para no mezclar
            # precio en formacion con el resultado real del contrato binario.
            for h in range(1, 5):
                if s.medido_cerrado[h - 1] or shift < h + 1:
                    continue
                ci = self._i_close(self.df_m15, shift - h)
                if ci == 0:
                    continue
                # Guarda de integridad: durante la precarga el feed se re-siembra
                # y alguna fila puede traer un precio que no pertenece a este
                # activo. Un cierre a mas de 12 ATR de la entrada no es un precio
                # real: no se registra y se reintenta en el siguiente tick.
                atr_ref = (s.atr14 * self.point) or (self.g_atr14_buffer[0] if self.g_atr14_buffer else 0.0)
                if atr_ref <= 0:
                    continue
                if abs(ci - s.entry_price) > atr_ref * 12.0:
                    if getattr(self, "g_mediciones_descartadas", 0) < 5:
                        self.g_mediciones_descartadas = getattr(self, "g_mediciones_descartadas", 0) + 1
                        print(f"Medicion h{h} descartada: cierre {ci} a {abs(ci - s.entry_price) / atr_ref:.1f} ATR de la entrada")
                    continue
                mfe_h = s.entry_price
                mae_h = s.entry_price
                for b in range(shift, shift - h - 1, -1):
                    hh = self._i_high(self.df_m15, b)
                    ll = self._i_low(self.df_m15, b)
                    if hh == 0 or ll == 0:
                        break
                    if (abs(hh - s.entry_price) > atr_ref * 12.0
                            or abs(ll - s.entry_price) > atr_ref * 12.0):
                        break
                    if s.direction == 1:
                        if hh > mfe_h:
                            mfe_h = hh
                        if ll < mae_h:
                            mae_h = ll
                    else:
                        if ll < mfe_h:
                            mfe_h = ll
                        if hh > mae_h:
                            mae_h = hh
                if s.direction == 1:
                    s.retorno_cerrado[h - 1] = (ci - s.entry_price) / self.point
                    s.mfe_cerrado[h - 1] = (mfe_h - s.entry_price) / self.point
                    s.mae_cerrado[h - 1] = (mae_h - s.entry_price) / self.point
                else:
                    s.retorno_cerrado[h - 1] = (s.entry_price - ci) / self.point
                    s.mfe_cerrado[h - 1] = (s.entry_price - mfe_h) / self.point
                    s.mae_cerrado[h - 1] = (s.entry_price - mae_h) / self.point
                s.medido_cerrado[h - 1] = True
                try:
                    import asyncio
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(self.db.guardar_resultado_senal(
                        signal_id=s.id, horizonte=h,
                        retorno=s.retorno_cerrado[h - 1],
                        mfe=s.mfe_cerrado[h - 1],
                        mae=s.mae_cerrado[h - 1]))
                    loop.close()
                except Exception as e:
                    print(f"DB resultado senal {s.id} h{h} fallo: {e}")

            idx = shift - 1
            if idx < 0 or idx >= 4 or s.measured[idx]:
                keep.append(s)
                continue

            close = self._i_close(self.df_m15, 0)
            if close == 0:
                keep.append(s)
                continue

            mfe = s.entry_price; mae = s.entry_price
            for b in range(shift, 0, -1):
                h = self._i_high(self.df_m15, b)
                l = self._i_low(self.df_m15, b)
                if h == 0 or l == 0:
                    break
                if s.direction == 1:
                    if h > mfe: mfe = h
                    if l < mae: mae = l
                else:
                    if l < mfe: mfe = l
                    if h > mae: mae = h

            ret = (close - s.entry_price) / self.point if s.direction == 1 else (s.entry_price - close) / self.point
            s.retorno[idx] = ret
            s.mfe[idx] = (mfe - s.entry_price) / self.point if s.direction == 1 else (s.entry_price - mfe) / self.point
            s.mae[idx] = (mae - s.entry_price) / self.point if s.direction == 1 else (s.entry_price - mae) / self.point
            s.measured[idx] = True
            s.signal_age_bars = shift
            # Migración G12: guardar en SQLite en lugar de CSV
            if not s.csv_written:
                import asyncio
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self.db.guardar_senal_core(
                    signal_id=s.id,
                    entry_time=s.entry_time,
                    symbol=s.symbol,
                    direction=s.direction,
                    entry_price=s.entry_price,
                    detector=s.detector,
                    tipo=s.tipo or "",
                    hipotesis_prob_min=s.hipotesis_prob_min or 0.0,
                    hipotesis_prob_max=s.hipotesis_prob_max or 0.0,
                    hipotesis_expiry_velas=s.hipotesis_expiry_velas or 0,
                    conviccion=s.conviccion or 0.0,
                    regimen_volatilidad=s.regimen_volatilidad or "",
                    fuente="deriv",
                ))
                loop.close()
                s.csv_written = True
            if idx == 3:
                s.completada = True
            keep.append(s)

        self.g_pending_signals = keep
        self.g_pending_ids = {s.id for s in self.g_pending_signals}
        # Migración G12: guardar pending en SQLite en lugar de CSV
        import asyncio
        loop = asyncio.new_event_loop()
        for s in self.g_pending_signals:
            loop.run_until_complete(self.db.marcar_cola_procesada(s.id))
        loop.close()

    def test_ntfy(self):
        msg = (
            "🔧 TEST — PivotRadar Hybrid v8.0\n"
            "EA iniciado correctamente.\n"
            f"Hora: {datetime.now().strftime('%Y.%m.%d %H:%M:%S')}\n"
            "✅ ARQUITECTURA PLUGIN ACTIVA\n"
            "✅ TODOS LOS DETECTORES INTRAVELA"
        )
        if self.alertas.send_ntfy_message(msg, forzar=True):
            print("Mensaje de prueba enviado")
        else:
            print("Fallo test")


if __name__ == "__main__":
    engine = PivotRadarEngine(symbol="EURUSD", modo_test=False, broker_tz_offset_hours=2)
    print("Motor v8.0 inicializado. Use on_data(df_m15, df_h1, df_h4, df_d1) para procesar.")
