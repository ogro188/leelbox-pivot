# -*- coding: utf-8 -*-
"""
Adaptador para integrar los detectores del Core (D0-D5) con el Kernel.
Permite usar la lógica existente de detectores en el nuevo sistema de backtesting.
"""
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from copy import deepcopy

logger = logging.getLogger(__name__)

# Importar tipos del kernel
from kernel.contrato import Contexto as KernelContexto, ActivoInfo
from core.base import Contexto as CoreContexto
from core.d0_estructura import EstructuraProvider
from core.estructuras import EstructuraRef


class CoreAdapter:
    """
    Adapta el Contexto del Kernel al formato esperado por los detectores del Core.
    Permite reutilizar toda la lógica de detectores D0-D5 existentes.
    """
    
    def __init__(self):
        self.core_ctx: Optional[CoreContexto] = None
        self.estructura_provider: Optional[EstructuraProvider] = None
    
    def adaptar_contexto(self, kernel_ctx: KernelContexto) -> CoreContexto:
        """
        Convierte un Contexto del Kernel al formato del Core.
        
        Args:
            kernel_ctx: Contexto desde el kernel con dataframes y estado
            
        Returns:
            Contexto compatible con los detectores del core
        """
        # Crear contexto del core
        core_ctx = CoreContexto()
        
        # Copiar DataFrames (mapeo de timeframes)
        core_ctx.df_m15 = kernel_ctx.df_m15
        core_ctx.df_h1 = kernel_ctx.df_h1
        core_ctx.df_h4 = kernel_ctx.df_h4
        core_ctx.df_d1 = kernel_ctx.df_d1
        
        # Copiar buffers de indicadores (referencias directas, no copias)
        core_ctx.g_atr8_buffer = kernel_ctx.g_atr8_buffer
        core_ctx.g_atr14_buffer = kernel_ctx.g_atr14_buffer
        core_ctx.g_atr30_buffer = kernel_ctx.g_atr30_buffer
        core_ctx.g_ema21_buffer = kernel_ctx.g_ema21_buffer
        core_ctx.g_ema50_buffer = kernel_ctx.g_ema50_buffer
        core_ctx.g_rsi14_buffer = kernel_ctx.g_rsi14_buffer
        core_ctx.g_ema50_d1_buffer = kernel_ctx.g_ema50_d1_buffer
        core_ctx.g_ema200_d1_buffer = kernel_ctx.g_ema200_d1_buffer
        core_ctx.g_ema20_h4_buffer = kernel_ctx.g_ema20_h4_buffer
        core_ctx.g_ema50_h4_buffer = kernel_ctx.g_ema50_h4_buffer
        # Nota: NO se mapean g_d1_trend_buffer, g_h4_trend_buffer, g_volatilidad_buffer,
        # g_zona_buffer. No existen en core.Contexto (usa strings trend_d1/regimen_vol).
        
        # Copiar métricas G
        core_ctx.g1 = kernel_ctx.g1
        core_ctx.g2 = kernel_ctx.g2
        core_ctx.g3 = kernel_ctx.g3
        core_ctx.g4 = kernel_ctx.g4
        
        # Copiar contexto temporal
        core_ctx.session = kernel_ctx.session
        core_ctx.kill_zone = kernel_ctx.kill_zone
        core_ctx.trend_d1 = kernel_ctx.trend_d1
        core_ctx.regimen_vol = kernel_ctx.regimen_vol
        
        # Copiar parámetros
        core_ctx.point = kernel_ctx.point
        core_ctx.broker_tz_offset = kernel_ctx.broker_tz_offset
        
        # Copiar funciones helper
        core_ctx.get_volume_ratio_cached = kernel_ctx.get_volume_ratio_cached
        core_ctx.get_volume_ratio = kernel_ctx.get_volume_ratio
        core_ctx.detect_mss_h4 = kernel_ctx.detect_mss_h4
        core_ctx.es_zona_premium_discount = kernel_ctx.es_zona_premium_discount
        core_ctx.evaluar_contexto_estructural = kernel_ctx.evaluar_contexto_estructural
        
        # Actualizar estructura usando D0
        # Intentar con H1 primero, si no existe usar M15 como fallback
        df_estructura = core_ctx.df_h1
        if df_estructura is None or len(df_estructura) <= 50:
            df_estructura = core_ctx.df_m15
        
        if df_estructura is not None and len(df_estructura) > 50:
            self.estructura_provider = EstructuraProvider(core_ctx)
            estructura = self.estructura_provider.actualizar()
            core_ctx.estructura = estructura
        
        self.core_ctx = core_ctx
        return core_ctx
    
    def obtener_estructura(self) -> Optional[EstructuraRef]:
        """Obtiene la estructura actual calculada por D0."""
        if self.core_ctx and self.core_ctx.estructura:
            return self.core_ctx.estructura
        return None
    
    def ejecutar_detectores(self, detectores: List[Any]) -> Dict[str, Any]:
        """
        Ejecuta una lista de detectores sobre el contexto actual.
        
        Args:
            detectores: Lista de instancias de detectores (D1, D2, D3, etc.)
            
        Returns:
            Diccionario con resultados por detector
        """
        if not self.core_ctx:
            raise ValueError("Debe llamar a adaptar_contexto() primero")
        
        resultados = {}
        for detector in detectores:
            try:
                # Los detectores clasifican internamente (A/B/C/D) y setean sig.tipo.
                # No se llama detector.clasificar() aquí: firmas varían por detector y
                # la clasificación externa ya está embebida en detectar().
                señal = detector.detectar(self.core_ctx)
                if señal:
                    resultados[detector.nombre] = {
                        "senal": señal,
                        "nombre": detector.nombre,
                    }
            except Exception as e:
                logger.error(f"Detector {detector.nombre} falló: {e}", exc_info=True)
                resultados[detector.nombre] = {"error": str(e)}
        
        return resultados


def aplicar_parametros(core_ctx, config) -> None:
    """
    Copia todos los parámetros inp_* requeridos por los detectores desde la
    configuración de la estrategia al core.Contexto.
    
    Args:
        core_ctx: core.base.Contexto (ya adaptado)
        config: ConfiguracionPivot con los atributos de configuración
    """
    mapping = {
        "inp_n_ruptura": "n_ruptura",
        "inp_d1_atr_threshold": "d1_atr_threshold",
        "inp_body_ratio_min": "body_ratio_min",
        "inp_d1_use_retest": "use_retest",
        "inp_d1_use_volume": "use_volume",
        "inp_d1_min_volume": "min_volume",
        "inp_sweep_n": "sweep_n",
        "inp_sweep_wick_min": "sweep_wick_min",
        "inp_reclaim_body_min": "reclaim_body_min",
        "inp_equal_hl_window": "equal_hl_window",
        "inp_equal_hl_tol": "equal_hl_tol",
        "inp_d2_anticipar": "d2_anticipar",
        "inp_fvg_min_size_atr": "fvg_min_size_atr",
        "inp_fvg_body_ratio": "fvg_body_ratio",
        "inp_fvg_mitig_umbral": "fvg_mitig_umbral",
        "inp_ob_lookback": "ob_lookback",
        "inp_ob_body_min": "ob_body_min",
        "inp_ob_impulse_min": "ob_impulse_min",
        "inp_mss_lookback_h4": "mss_lookback_h4",
        "inp_mss_max_age_h4_bars": "mss_max_age_h4_bars",
        "inp_pivot_depth": "pivot_depth",
        "inp_pivot_lookback": "pivot_lookback",
        "inp_sweep_distancia": "sweep_distancia",
        "inp_zona_margen": "zona_margen",
        "inp_peso_estructural": "peso_estructural",
    }
    for inp_attr, cfg_attr in mapping.items():
        value = getattr(config, cfg_attr, None)
        if value is not None:
            setattr(core_ctx, inp_attr, value)


def calcular_indicadores_core(df: pd.DataFrame) -> Dict[str, List[float]]:
    """
    Calcula todos los indicadores necesarios para los detectores del core.
    
    Args:
        df: DataFrame con columnas open, high, low, close, tick_volume
        
    Returns:
        Diccionario con buffers de indicadores (índice 0 = más reciente)
    """
    if df is None or len(df) == 0:
        return {}
    
    # Calcular ATRs
    high = df['high']
    low = df['low']
    close = df['close']
    close_prev = close.shift(1)
    
    tr = pd.concat([
        high - low,
        (high - close_prev).abs(),
        (low - close_prev).abs()
    ], axis=1).max(axis=1)
    
    atr8 = tr.ewm(span=8, adjust=False).mean()
    atr14 = tr.ewm(span=14, adjust=False).mean()
    atr30 = tr.ewm(span=30, adjust=False).mean()
    
    # Calcular EMAs
    ema21 = close.ewm(span=21, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    
    # Calcular RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    rsi14 = 100 - (100 / (1 + rs))
    
    # Convertir a buffers (índice 0 = último valor)
    def to_buffer(series: pd.Series) -> List[float]:
        return [float(x) if not pd.isna(x) else 0.0 for x in series.iloc[::-1].values]
    
    return {
        'g_atr8_buffer': to_buffer(atr8),
        'g_atr14_buffer': to_buffer(atr14),
        'g_atr30_buffer': to_buffer(atr30),
        'g_ema21_buffer': to_buffer(ema21),
        'g_ema50_buffer': to_buffer(ema50),
        'g_rsi14_buffer': to_buffer(rsi14),
    }


def actualizar_contexto_con_indicadores(ctx, timeframe: str = "M15"):
    """Actualiza buffers de indicadores reemplazando las listas completas (tamaño fijo).

    El core espera buffers donde el índice 0 es el valor más reciente.
    append()/extend() acumularían valores históricos y corromperían ATR/EMA/RSI.
    """
    df = getattr(ctx, f"df_{timeframe.lower()}", None)
    # En el runtime los DataFrames pueden ser listas; solo operar sobre DataFrames reales
    if df is None or not hasattr(df, "columns") or len(df) == 0:
        return

    def to_buffer(series, max_size: int = 55) -> List[float]:
        vals = series.to_numpy(dtype=float)[::-1][:max_size]
        return np.nan_to_num(vals, nan=0.0).tolist()

    precalc_cols = ["atr8", "atr14", "atr30", "ema21", "ema50", "rsi14"]
    if all(c in df.columns for c in precalc_cols):
        # DataFrame con indicadores precalculados (CSVFeed / BacktestEngine)
        ctx.g_atr8_buffer = to_buffer(df['atr8'])
        ctx.g_atr14_buffer = to_buffer(df['atr14'])
        ctx.g_atr30_buffer = to_buffer(df['atr30'])
        ctx.g_ema21_buffer = to_buffer(df['ema21'])
        ctx.g_ema50_buffer = to_buffer(df['ema50'])
        ctx.g_rsi14_buffer = to_buffer(df['rsi14'])
    else:
        # Fallback: recalcular (CSV antiguo sin columnas de indicadores)
        indicadores = calcular_indicadores_core(df)
        for attr in (
            "g_atr8_buffer", "g_atr14_buffer", "g_atr30_buffer",
            "g_ema21_buffer", "g_ema50_buffer", "g_rsi14_buffer",
        ):
            buf = indicadores.get(attr, [])
            if buf:
                setattr(ctx, attr, buf[:55])
