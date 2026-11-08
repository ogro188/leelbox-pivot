#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Base de detectores: interfaz común + Contexto compartido."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Tuple
import pandas as pd
import numpy as np


@dataclass
class Contexto:
    """Snapshot inmutable de todo lo que un detector puede necesitar."""
    # DataFrames
    df_m15: Optional[pd.DataFrame] = None
    df_h1:  Optional[pd.DataFrame] = None
    df_h4:  Optional[pd.DataFrame] = None
    df_d1:  Optional[pd.DataFrame] = None

    # Buffers de indicadores (listas con índice 0 = más reciente)
    g_atr8_buffer:  List[float] = field(default_factory=list)
    g_atr14_buffer: List[float] = field(default_factory=list)
    g_atr30_buffer: List[float] = field(default_factory=list)
    g_ema21_buffer: List[float] = field(default_factory=list)
    g_ema50_buffer: List[float] = field(default_factory=list)
    g_rsi14_buffer: List[float] = field(default_factory=list)
    g_ema50_d1_buffer:  List[float] = field(default_factory=list)
    g_ema200_d1_buffer: List[float] = field(default_factory=list)
    g_ema20_h4_buffer:  List[float] = field(default_factory=list)
    g_ema50_h4_buffer:  List[float] = field(default_factory=list)

    # Estructura D0
    estructura: Optional[object] = None   # EstructuraRef

    # Caches
    mss_cache: Optional[object] = None     # MSSCache
    zona_cache: Optional[object] = None    # ZonaCache

    # Caché de columnas numpy por DataFrame (clave id(df), no df.attrs:
    # mutar attrs degrada el rendimiento de df.iloc en pandas 3.x)
    _pivot_cols_cache: dict = field(default_factory=dict, repr=False, compare=False)

    # Métricas G (ya calculadas una vez por vela)
    g1: float = 0.0
    g2: float = 0.0
    g3: float = 0.0
    g4: float = 0.0

    # Contexto temporal
    session: str = "OUT"
    kill_zone: str = "NONE"
    trend_d1: str = "NEUTRO"
    regimen_vol: str = "NORMAL"

    # Parámetros (todos los inp_*)
    point: float = 0.00001
    broker_tz_offset: timezone = field(default_factory=lambda: timezone(timedelta(hours=2)))

    # Helpers de parámetros (copia para detectores)
    inp_n_ruptura: int = 4
    inp_d1_atr_threshold: float = 0.50
    inp_body_ratio_min: float = 0.40
    inp_d1_use_retest: bool = True
    inp_d1_use_volume: bool = True
    inp_d1_min_volume: float = 1.2
    inp_sweep_n: int = 6
    inp_sweep_wick_min: float = 0.55
    inp_reclaim_body_min: float = 0.55
    inp_equal_hl_window: int = 10
    inp_equal_hl_tol: float = 0.15
    inp_d2_anticipar: bool = True
    inp_fvg_min_size_atr: float = 0.20
    inp_fvg_body_ratio: float = 0.55
    inp_fvg_mitig_umbral: float = 0.50
    inp_ob_lookback: int = 12
    inp_ob_body_min: float = 0.40
    inp_ob_impulse_min: float = 0.70
    inp_mss_lookback_h4: int = 20
    inp_mss_max_age_h4_bars: int = 12
    inp_pivot_depth: int = 2
    inp_pivot_lookback: int = 24
    inp_sweep_distancia: float = 1.5
    inp_zona_margen: float = 0.5
    inp_peso_estructural: float = 0.25

    # Funciones helper inyectadas (se asignan desde el orquestador)
    get_volume_ratio_cached: callable = field(default=lambda *a, **k: 1.0, repr=False)
    get_volume_ratio:      callable = field(default=lambda *a, **k: 1.0, repr=False)
    detect_mss_h4:         callable = field(default=lambda: (False,0,"",0.0), repr=False)
    es_zona_premium_discount: callable = field(default=lambda nivel: (False,"NEUTRO"), repr=False)
    evaluar_contexto_estructural: callable = field(default=lambda *a: (50.0,0.0), repr=False)

    # -----------------------------------------------------------------
    # Helpers de series temporales (copia idéntica del motor original)
    # -----------------------------------------------------------------
    def _col_cache(self, df: Optional[pd.DataFrame]) -> Optional[Dict[str, object]]:
        """Caché de columnas numpy por DataFrame (evita lookups pandas por fila).

        Almacenado en el contexto (no en df.attrs): en pandas 3.x, mutar
        df.attrs degrada el rendimiento de df.iloc sobre el mismo objeto.
        """
        if df is None:
            return None
        cache = self._pivot_cols_cache
        key = id(df)
        cols = cache.get(key)
        if cols is None:
            cols = {}
            for col in ("open", "high", "low", "close"):
                if col in df.columns:
                    cols[col] = df[col].to_numpy(dtype=float)
            vol_col = "tick_volume" if "tick_volume" in df.columns else ("volume" if "volume" in df.columns else None)
            if vol_col is not None:
                cols["volume"] = df[vol_col].to_numpy(dtype=float)
            # Guardar el índice directamente: convertir DatetimeIndex a numpy
            # (np.asarray(df.index)) es ~2ms por DataFrame en cada barra del
            # backtest. La lectura escalar por índice negativo es igual de rápida.
            cols["index"] = df.index
            cache[key] = cols
        return cols

    def _i_high(self, df: pd.DataFrame, shift: int) -> float:
        if df is None or shift < 0 or shift >= len(df):
            return 0.0
        cache = self._col_cache(df)
        if cache is not None:
            return float(cache["high"][-(shift + 1)])
        return float(df.iloc[-(shift + 1)]["high"])

    def _i_low(self, df: pd.DataFrame, shift: int) -> float:
        if df is None or shift < 0 or shift >= len(df):
            return 0.0
        cache = self._col_cache(df)
        if cache is not None:
            return float(cache["low"][-(shift + 1)])
        return float(df.iloc[-(shift + 1)]["low"])

    def _i_close(self, df: pd.DataFrame, shift: int) -> float:
        if df is None or shift < 0 or shift >= len(df):
            return 0.0
        cache = self._col_cache(df)
        if cache is not None:
            return float(cache["close"][-(shift + 1)])
        return float(df.iloc[-(shift + 1)]["close"])

    def _i_open(self, df: pd.DataFrame, shift: int) -> float:
        if df is None or shift < 0 or shift >= len(df):
            return 0.0
        cache = self._col_cache(df)
        if cache is not None:
            return float(cache["open"][-(shift + 1)])
        return float(df.iloc[-(shift + 1)]["open"])

    def _i_volume(self, df: pd.DataFrame, shift: int) -> int:
        if df is None or shift < 0 or shift >= len(df):
            return 0
        cache = self._col_cache(df)
        if cache is not None:
            vol = cache.get("volume")
            if vol is not None:
                return int(vol[-(shift + 1)])
            return 0
        row = df.iloc[-(shift + 1)]
        col = "tick_volume" if "tick_volume" in df.columns else "volume"
        return int(row[col])

    def _i_time(self, df: pd.DataFrame, shift: int) -> datetime:
        if df is None or shift < 0 or shift >= len(df):
            return datetime(1970, 1, 1, tzinfo=timezone.utc)
        cache = self._col_cache(df)
        if cache is not None:
            t = cache["index"][-(shift + 1)]
            if isinstance(t, pd.Timestamp):
                return t.to_pydatetime()
            return t
        t = df.index[-(shift + 1)]
        if isinstance(t, pd.Timestamp):
            return t.to_pydatetime()
        return t


class Detector(ABC):
    @property
    @abstractmethod
    def nombre(self) -> str: ...

    @abstractmethod
    def detectar(self, ctx: Contexto) -> Optional[object]:  # -> Optional[Signal]
        """Retorna Signal() parcial si hay setup, None si no."""
        ...

    @abstractmethod
    def clasificar(self, sig: object, ctx: Contexto) -> str:
        """Retorna 'A', 'B', 'C' o 'D'."""
        ...
