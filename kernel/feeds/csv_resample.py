# -*- coding: utf-8 -*-
"""
Utilidades de resampling para generar timeframes mayores desde M15.
Solución al bug 8.1: permite derivar H1/H4/D1 automáticamente.
"""
import logging
import pandas as pd
from typing import Dict

logger = logging.getLogger(__name__)

def resamplear_ohlc(df_base: pd.DataFrame, timeframe_destino: str) -> pd.DataFrame:
    """
    Deriva un DataFrame OHLC de timeframe mayor a partir de uno de mayor resolución.
    Ej: M15 -> H1, H4, D1.
    
    Args:
        df_base: DataFrame con índice datetime y columnas OHLCV
        timeframe_destino: "H1", "H4", "D1"
    
    Returns:
        DataFrame resampleado
    """
    reglas = {
        "H1": "60min", 
        "H4": "240min", 
        "D1": "1440min",
    }
    
    if timeframe_destino not in reglas:
        raise ValueError(f"No se puede resamplear a {timeframe_destino}. Use H1, H4 o D1")

    regla = reglas[timeframe_destino]
    
    # Asegurar índice datetime
    df_work = df_base.copy()
    if not isinstance(df_work.index, pd.DatetimeIndex):
        df_work.index = pd.to_datetime(df_work.index)
        
    agg = df_work.resample(regla).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(subset=["open"])  # descartar periodos sin velas base

    return agg


def generar_timeframes_desde_m15(
    df_m15: pd.DataFrame, 
    timeframes: list = ["H1", "H4", "D1"]
) -> Dict[str, pd.DataFrame]:
    """
    Genera múltiples timeframes desde un DataFrame M15 base.
    
    Args:
        df_m15: DataFrame M15 original
        timeframes: Lista de timeframes a generar
    
    Returns:
        Diccionario {timeframe: DataFrame}
    """
    resultados = {}
    for tf in timeframes:
        try:
            resultados[tf] = resamplear_ohlc(df_m15, tf)
        except Exception as e:
            logger.error(f"Error generando {tf}: {e}")
    
    return resultados
