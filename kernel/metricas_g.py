# -*- coding: utf-8 -*-
"""
Módulo para cálculo de métricas G (G1-G4) UNA SOLA VEZ por barra.
Elimina la triplicación de cálculos de indicadores en el sistema.
"""
import pandas as pd
import ta
from typing import Optional
from kernel.contrato import GMetrics


def calcular_zona_premium_discount(m15: pd.DataFrame, h4: pd.DataFrame) -> str:
    """
    Determina si el precio está en zona PREMIUM, DISCOUNT o NEUTRAL.
    Usa el rango de las últimas 50 velas H4.
    """
    if m15 is None or h4 is None or len(h4) < 50:
        return "NEUTRAL"
    
    # Rango H4 últimas 50 velas
    highest = h4["high"].iloc[-50:].max()
    lowest = h4["low"].iloc[-50:].min()
    range_h4 = highest - lowest
    
    if range_h4 == 0:
        return "NEUTRAL"
    
    # Precio actual relativo al rango
    price = m15["close"].iloc[-1]
    ratio = (price - lowest) / range_h4
    
    if ratio > 0.7:
        return "PREMIUM"
    elif ratio < 0.3:
        return "DISCOUNT"
    else:
        return "NEUTRAL"


def calcular_metricas_g(ctx) -> GMetrics:
    """
    Calcula todas las métricas G UNA SOLA VEZ por barra.
    Usa los DataFrames ya presentes en el contexto.
    
    Args:
        ctx: Contexto con dataframes m15, h1, h4, d1
        
    Returns:
        GMetrics con todas las métricas calculadas
    """
    m15 = ctx.df_m15
    h4 = ctx.df_h4
    d1 = ctx.df_d1
    
    # ATRs
    atr8 = ta.atr(m15["high"], m15["low"], m15["close"], length=8).iloc[-1]
    atr14 = ta.atr(m15["high"], m15["low"], m15["close"], length=14).iloc[-1]
    atr50 = ta.atr(m15["high"], m15["low"], m15["close"], length=50).iloc[-1]
    
    # EMA50 y distancia
    ema50 = ta.ema(m15["close"], length=50).iloc[-1]
    precio = m15["close"].iloc[-1]
    ema_dist = (precio - ema50) / atr14 if atr14 != 0 else 0.0
    
    # Ángulo EMA (pendiente últimas 3 barras)
    ema_serie = ta.ema(m15["close"], length=50)
    if len(ema_serie) >= 4:
        ema_angulo = (ema_serie.iloc[-1] - ema_serie.iloc[-4]) / (3 * atr14) if atr14 != 0 else 0.0
    else:
        ema_angulo = 0.0
    
    # RSI14
    rsi14 = ta.rsi(m15["close"], length=14).iloc[-1]
    
    # Tendencias D1/H4
    if len(d1) >= 50:
        d1_ema50 = ta.ema(d1["close"], length=50).iloc[-1]
        d1_trend = 1 if d1["close"].iloc[-1] > d1_ema50 else -1
    else:
        d1_trend = 0
    
    if len(h4) >= 50:
        h4_ema50 = ta.ema(h4["close"], length=50).iloc[-1]
        h4_trend = 1 if h4["close"].iloc[-1] > h4_ema50 else -1
    else:
        h4_trend = 0
    
    # Volatilidad relativa
    g_volatilidad = round(float(atr14 / atr50) if atr50 != 0 else 1.0, 4)
    
    # Zona premium/discount
    zona = calcular_zona_premium_discount(m15, h4)
    
    return GMetrics(
        g_atr8=round(float(atr8), 6),
        g_atr14=round(float(atr14), 6),
        g_atr50=round(float(atr50), 6),
        g_ema50_dist=round(float(ema_dist), 4),
        g_ema50_angulo=round(float(ema_angulo), 4),
        g_rsi14=round(float(rsi14), 2),
        g_d1_trend=int(d1_trend),
        g_h4_trend=int(h4_trend),
        g_volatilidad=g_volatilidad,
        g_zona=zona,
    )
