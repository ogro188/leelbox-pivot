#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aceleradores SOLO para replay. No se importan desde produccion.

Reemplaza, en el proceso de analisis, los metodos del motor que mas tiempo
consumen:

  - _update_indicators: calcula ATR/EMA/RSI con numpy en vez de pandas.
  - detect_mss_h4: evita ~240 accesos .iloc por llamada.
  - es_zona_premium_discount: idem.
  - _i_high/_i_low/_i_close/_i_open/_i_volume: cache de columnas numpy.

Cada reemplazo replica la logica original linea por linea. `verificar()`
compara los buffers y los resultados contra el motor sin tocar para demostrar
que son identicos antes de confiar en el replay.
"""
from __future__ import annotations

import types

import numpy as np
import pandas as pd

ATR_BUFFER_SIZE = 55


def _cols(self, df):
    """Cache de columnas numpy por DataFrame, con referencia para evitar id reuse."""
    cache = getattr(self, "_fast_cols_cache", None)
    if cache is None:
        cache = {}
        self._fast_cols_cache = cache
    key = id(df)
    ent = cache.get(key)
    if ent is not None and ent[0] is df:
        return ent[1]
    cols = {}
    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            cols[col] = df[col].to_numpy(dtype=float)
    vol_col = "tick_volume" if "tick_volume" in df.columns else ("volume" if "volume" in df.columns else None)
    if vol_col is not None:
        cols["volume"] = df[vol_col].to_numpy(dtype=float)
    cols["index"] = df.index
    if len(cache) > 12:
        cache.clear()
    cache[key] = (df, cols)
    return cols


def fast_i_high(self, df, shift):
    if df is None or shift < 0 or shift >= len(df):
        return 0.0
    return float(_cols(self, df)["high"][-(shift + 1)])


def fast_i_low(self, df, shift):
    if df is None or shift < 0 or shift >= len(df):
        return 0.0
    return float(_cols(self, df)["low"][-(shift + 1)])


def fast_i_close(self, df, shift):
    if df is None or shift < 0 or shift >= len(df):
        return 0.0
    return float(_cols(self, df)["close"][-(shift + 1)])


def fast_i_open(self, df, shift):
    if df is None or shift < 0 or shift >= len(df):
        return 0.0
    return float(_cols(self, df)["open"][-(shift + 1)])


def fast_i_volume(self, df, shift):
    if df is None or shift < 0 or shift >= len(df):
        return 0
    vol = _cols(self, df).get("volume")
    if vol is None:
        return 0
    return int(vol[-(shift + 1)])


def fast_i_time(self, df, shift):
    if df is None or shift < 0 or shift >= len(df):
        from datetime import datetime, timezone
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    t = df.index[-(shift + 1)]
    if isinstance(t, pd.Timestamp):
        return t.to_pydatetime()
    return t


def fast_update_indicators(self):
    df = self.df_m15
    if df is None or len(df) < 55:
        return False

    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)

    prev_close = np.empty_like(close)
    prev_close[0] = np.nan
    prev_close[1:] = close[:-1]
    tr = np.maximum(np.maximum(high - low, np.abs(high - prev_close)), np.abs(low - prev_close))
    tr[0] = high[0] - low[0]

    def atr(period):
        return pd.Series(tr).ewm(alpha=1.0 / period, adjust=False).mean().to_numpy()

    def ema(values, span):
        return pd.Series(values).ewm(span=span, adjust=False).mean().to_numpy()

    self.g_atr8_buffer = atr(8)[-ATR_BUFFER_SIZE:][::-1].tolist()
    self.g_atr14_buffer = atr(14)[-ATR_BUFFER_SIZE:][::-1].tolist()
    self.g_atr30_buffer = atr(30)[-ATR_BUFFER_SIZE:][::-1].tolist()
    self.g_ema21_buffer = ema(close, 21)[-ATR_BUFFER_SIZE:][::-1].tolist()
    self.g_ema50_buffer = ema(close, 50)[-ATR_BUFFER_SIZE:][::-1].tolist()

    s = pd.Series(close)
    delta = s.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1.0 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss
    rsi = (100.0 - (100.0 / (1.0 + rs))).to_numpy()
    self.g_rsi14_buffer = rsi[-ATR_BUFFER_SIZE:][::-1].tolist()

    if self.df_d1 is not None and len(self.df_d1) >= 205:
        d1c = self.df_d1["close"].to_numpy(dtype=float)
        self.g_ema50_d1_buffer = ema(d1c, 50)[-5:][::-1].tolist()
        self.g_ema200_d1_buffer = ema(d1c, 200)[-5:][::-1].tolist()
    else:
        self.g_ema50_d1_buffer = []
        self.g_ema200_d1_buffer = []

    if self.df_h4 is not None and len(self.df_h4) >= 20:
        h4c = self.df_h4["close"].to_numpy(dtype=float)
        self.g_ema20_h4_buffer = ema(h4c, 20)[-20:][::-1].tolist()
        self.g_ema50_h4_buffer = ema(h4c, 50)[-20:][::-1].tolist()
    else:
        self.g_ema20_h4_buffer = []
        self.g_ema50_h4_buffer = []
    return True


def fast_detect_mss_h4(self):
    df = self.df_h4
    if df is None or len(df) < 50:
        return False, 0, "", 0.0
    current_h4_bar = df.index[-1]
    if isinstance(current_h4_bar, pd.Timestamp):
        current_h4_bar = current_h4_bar.to_pydatetime()
    if self.g_mss_cache.valid and self.g_mss_cache.calc_time == current_h4_bar:
        return True, self.g_mss_cache.bars_ago, self.g_mss_cache.dir, self.g_mss_cache.level

    cols = _cols(self, df)
    close = cols["close"]
    high = cols["high"]
    low = cols["low"]
    n = len(df)

    max_scan = min(self.inp_mss_max_age_h4_bars, n - 3)
    for i in range(1, max_scan + 1):
        close_i = float(close[-(i + 1)])
        if close_i == 0:
            continue
        prior_high = 0.0
        prior_low = 999999.0
        window_start = i + 1
        window_end = min(i + 1 + self.inp_mss_lookback_h4, n)
        for k in range(window_start, window_end):
            hk = float(high[-(k + 1)])
            lk = float(low[-(k + 1)])
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


def fast_zona_premium_discount(self, nivel):
    current_bar = self._i_time(self.df_m15, 0)
    if self.g_zona_cache.valid and self.g_zona_cache.calc_time == current_bar:
        zona = "PREMIUM" if nivel > self.g_zona_cache.mid else "DISCOUNT"
        return True, zona

    cols = _cols(self, self.df_m15)
    high = cols["high"]
    low = cols["low"]
    n = len(high)
    max_high = 0.0
    min_low = 999999.0
    for i in range(1, 51):
        if i >= n:
            break
        h = float(high[-(i + 1)])
        l = float(low[-(i + 1)])
        if h == 0 or l == 0:
            break
        if h > max_high:
            max_high = h
        if l < min_low:
            min_low = l
    if max_high > 0 and min_low > 0 and max_high > min_low:
        mid = (max_high + min_low) / 2.0
        self.g_zona_cache.valid = True
        self.g_zona_cache.calc_time = current_bar
        self.g_zona_cache.mid = mid
        zona = "PREMIUM" if nivel > mid else "DISCOUNT"
        return True, zona
    return False, "NEUTRO"


def install_fast_engine(engine_cls):
    """Aplica los reemplazos a la clase del motor en este proceso."""
    engine_cls._i_high = fast_i_high
    engine_cls._i_low = fast_i_low
    engine_cls._i_close = fast_i_close
    engine_cls._i_open = fast_i_open
    engine_cls._i_volume = fast_i_volume
    engine_cls._i_time = fast_i_time
    engine_cls._update_indicators = fast_update_indicators
    engine_cls.detect_mss_h4 = fast_detect_mss_h4
    engine_cls.es_zona_premium_discount = fast_zona_premium_discount
    return engine_cls
