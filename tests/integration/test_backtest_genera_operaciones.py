# -*- coding: utf-8 -*-
"""
Test crítico de la Fase 8.1: Verifica que el backtest genera al menos una operación
con datos reales de 6 meses. Si falla, hay un bug estructural.
"""
import pytest
from datetime import datetime, timezone
from kernel.activos_loader import cargar_activo
from estrategias.registro import registro
from kernel.feeds.csv import CSVFeed
from kernel.backtest import BacktestEngine

def test_backtest_genera_al_menos_una_operacion_en_6_meses_reales():
    """
    Test de humo: con datos reales de 6 meses y confianza_minima baja,
    el sistema DEBE poder generar al menos una operación.
    """
    activo = cargar_activo("EURUSD")
    estrategia = registro.fabricar("PIVOT")
    
    # Usar dataset real de 6 meses (ya existen H1/H4/D1 generados)
    data_path = "data/eurusd_m15_real.csv"
    
    feed = CSVFeed(
        path=data_path, 
        timeframe="M15", 
        symbol=activo.simbolo,
    )
    
    engine = BacktestEngine(
        estrategia=estrategia,
        activo=activo,
        capital_inicial=10000.0,
        riesgo_por_operacion=0.01,
        slippage_pips=0.5,
        comision_lote=0.0,
    )
    
    resultado = engine.ejecutar(
        feeds={"M15": feed},
        params_estrategia={"confianza_minima": 40.0},  # Baja para asegurar señales
    )
    
    assert resultado.total_operaciones > 0, (
        f"0 operaciones en 6 meses de datos reales indica un bug estructural. "
        f"Resultado completo: {resultado.to_dict()}"
    )
    
    print(f"\n✅ Test pasado: {resultado.total_operaciones} operaciones generadas")
    print(f"   WinRate: {resultado.winrate:.2f}%")
    print(f"   Profit Factor: {resultado.profit_factor:.2f}")
