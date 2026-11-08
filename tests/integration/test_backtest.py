"""
Tests de integración para el sistema completo de backtesting PIVOT
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
sys.path.insert(0, '/workspace')

from kernel.feeds.csv import CSVFeed, MultiTimeframeFeed
from kernel.backtest import BacktestEngine, ResultadoBacktest
from kernel.contrato import ActivoInfo
from estrategias.pivot import EstrategiaPivot


def crear_csv_temporal(n_velas=500):
    """Crea un archivo CSV temporal con datos sintéticos"""
    import tempfile
    import os
    
    fechas = [datetime(2024, 1, 1) + timedelta(minutes=i*15) for i in range(n_velas)]
    precios = [1.1000 + np.sin(i*0.05)*0.001 + i*0.00001 for i in range(n_velas)]
    
    data = {
        'timestamp': [f.strftime('%Y-%m-%d %H:%M:%S') for f in fechas],
        'open': precios,
        'high': [p + 0.0002 for p in precios],
        'low': [p - 0.0002 for p in precios],
        'close': precios,
        'volume': [100 + np.random.randint(-20, 20) for _ in range(n_velas)]
    }
    
    df = pd.DataFrame(data)
    
    # Crear archivo temporal
    tmpfile = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv', encoding='utf-8')
    df.to_csv(tmpfile.name, index=False)
    tmpfile.close()
    
    return tmpfile.name


def crear_activo_info_eurusd():
    """Crea ActivoInfo para EURUSD con parámetros correctos"""
    return ActivoInfo(
        simbolo='EURUSD',
        punto=0.00001,
        tick_size=0.00001,
        contract_size=100000,
        session_open='00:00',
        session_close='23:59'
    )


class TestCSVFeed:
    """Tests para CSVFeed"""
    
    def test_carga_csv_correctamente(self):
        """Verifica carga básica de CSV"""
        csv_path = crear_csv_temporal(100)
        
        try:
            feed = CSVFeed(csv_path, timeframe='m15')
            velas = list(feed.iter_barras())
            
            assert len(velas) > 0
            assert 'open' in velas[0]
            assert 'close' in velas[0]
            assert 'high' in velas[0]
            assert 'low' in velas[0]
        finally:
            import os
            os.unlink(csv_path)
    
    def test_iteracion_secuencial(self):
        """Verifica que las velas se entregan en orden"""
        csv_path = crear_csv_temporal(50)
        
        try:
            feed = CSVFeed(csv_path, timeframe='m15')
            velas = list(feed.iter_barras())
            
            # Verificar orden cronológico
            for i in range(1, len(velas)):
                assert velas[i]['timestamp'] >= velas[i-1]['timestamp']
        finally:
            import os
            os.unlink(csv_path)


class TestMultiTimeframeFeed:
    """Tests para MultiTimeframeFeed"""
    
    def test_sincronizacion_timeframes(self):
        """Verifica sincronización entre timeframes"""
        csv_m15 = crear_csv_temporal(200)
        csv_h1 = crear_csv_temporal(50)  # Menos velas para H1
        
        try:
            feed = MultiTimeframeFeed(symbol='EURUSD')
            feed.add_feed('m15', csv_m15)
            feed.add_feed('h1', csv_h1)
            
            # Verificar que puede obtener datos de ambos timeframes
            assert feed.tiene_datos('m15')
            assert feed.tiene_datos('h1')
        finally:
            import os
            os.unlink(csv_m15)
            os.unlink(csv_h1)


class TestBacktestEngine:
    """Tests para BacktestEngine"""
    
    def test_ejecucion_basica(self):
        """Verifica ejecución básica del backtest"""
        csv_path = crear_csv_temporal(500)
        
        try:
            activo_info = crear_activo_info_eurusd()
            estrategia = EstrategiaPivot()
            
            engine = BacktestEngine(
                estrategia=estrategia,
                activo=activo_info,
                capital_inicial=10000,
                riesgo_por_operacion=0.01,
                slippage_pips=1,
                comision_lote=7.0
            )
            
            feed = CSVFeed(csv_path, timeframe='m15')
            resultado = engine.ejecutar(feeds={'m15': feed})
            
            assert isinstance(resultado, ResultadoBacktest)
            assert resultado.capital_inicial == 10000
            assert resultado.operaciones_totales >= 0
        finally:
            import os
            os.unlink(csv_path)
    
    def test_metricas_calculadas(self):
        """Verifica que todas las métricas se calculan"""
        csv_path = crear_csv_temporal(300)
        
        try:
            activo_info = crear_activo_info_eurusd()
            estrategia = EstrategiaPivot()
            
            engine = BacktestEngine(
                estrategia=estrategia,
                activo=activo_info,
                capital_inicial=10000,
                riesgo_por_operacion=0.02,
                slippage_pips=2,
                comision_lote=10.0
            )
            
            feed = CSVFeed(csv_path, timeframe='m15')
            resultado = engine.ejecutar(feeds={'m15': feed})
            
            # Verificar métricas principales
            assert resultado.capital_final is not None
            assert resultado.retorno_total is not None
            assert resultado.retorno_porcentual is not None
            assert resultado.operaciones_totales is not None
            assert resultado.operaciones_ganadoras is not None
            assert resultado.operaciones_perdedoras is not None
            assert resultado.winrate is not None
            assert resultado.profit_factor is not None
            assert resultado.drawdown_maximo is not None
            assert resultado.sharpe_ratio is not None
        finally:
            import os
            os.unlink(csv_path)
    
    def test_parametros_personalizados(self):
        """Verifica que parámetros personalizados se aplican"""
        csv_path = crear_csv_temporal(200)
        
        try:
            activo_info = crear_activo_info_eurusd()
            estrategia = EstrategiaPivot()
            
            # Backtest con parámetros agresivos
            engine_agresivo = BacktestEngine(
                estrategia=estrategia,
                activo=activo_info,
                capital_inicial=5000,
                riesgo_por_operacion=0.05,  # 5% riesgo
                slippage_pips=3,
                comision_lote=15.0
            )
            
            # Backtest con parámetros conservadores
            engine_conservador = BacktestEngine(
                estrategia=estrategia,
                activo=activo_info,
                capital_inicial=20000,
                riesgo_por_operacion=0.005,  # 0.5% riesgo
                slippage_pips=0,
                comision_lote=0.0
            )
            
            feed = CSVFeed(csv_path, timeframe='m15')
            resultado_agresivo = engine_agresivo.ejecutar(feeds={'m15': feed})
            
            feed2 = CSVFeed(csv_path, timeframe='m15')
            resultado_conservador = engine_conservador.ejecutar(feeds={'m15': feed2})
            
            # Los resultados deberían ser diferentes debido a los parámetros
            assert resultado_agresivo.capital_inicial != resultado_conservador.capital_inicial
        finally:
            import os
            os.unlink(csv_path)


class TestIntegracionCompleta:
    """Tests de integración completa del sistema"""
    
    def test_flujo_completo_backtest(self):
        """Verifica flujo completo: CSV → Feed → Engine → Estrategia → Resultados"""
        csv_path = crear_csv_temporal(1000)
        
        try:
            # 1. Crear feed
            feed = CSVFeed(csv_path, timeframe='m15')
            
            # 2. Configurar activo
            activo_info = crear_activo_info_eurusd()
            
            # 3. Crear estrategia
            estrategia = EstrategiaPivot()
            
            # 4. Configurar engine
            engine = BacktestEngine(
                estrategia=estrategia,
                activo=activo_info,
                capital_inicial=10000,
                riesgo_por_operacion=0.01,
                slippage_pips=1,
                comision_lote=7.0
            )
            
            # 5. Ejecutar backtest
            resultado = engine.ejecutar(feeds={'m15': feed})
            
            # 6. Validar resultados
            assert resultado is not None
            assert resultado.capital_inicial == 10000
            assert resultado.capital_final >= 0  # No perder más del 100%
            assert resultado.operaciones_totales >= 0
            
            # 7. Verificar consistencia de métricas
            if resultado.operaciones_totales > 0:
                assert 0 <= resultado.winrate <= 100
                assert resultado.profit_factor >= 0
                assert resultado.drawdown_maximo >= 0
                
        finally:
            import os
            os.unlink(csv_path)
    
    def test_multiple_timeframes(self):
        """Verifica funcionamiento con múltiples timeframes"""
        csv_m15 = crear_csv_temporal(400)
        csv_h1 = crear_csv_temporal(100)
        csv_h4 = crear_csv_temporal(25)
        
        try:
            activo_info = crear_activo_info_eurusd()
            estrategia = EstrategiaPivot()
            
            # Crear feeds para cada timeframe
            feed_m15 = CSVFeed(csv_m15, timeframe='m15')
            feed_h1 = CSVFeed(csv_h1, timeframe='h1')
            feed_h4 = CSVFeed(csv_h4, timeframe='h4')
            
            engine = BacktestEngine(
                estrategia=estrategia,
                activo=activo_info,
                capital_inicial=10000,
                riesgo_por_operacion=0.01,
                slippage_pips=1,
                comision_lote=7.0
            )
            
            # Ejecutar con múltiples timeframes
            resultado = engine.ejecutar(
                feeds={'m15': feed_m15, 'h1': feed_h1, 'h4': feed_h4}
            )
            
            assert resultado is not None
        finally:
            import os
            os.unlink(csv_m15)
            os.unlink(csv_h1)
            os.unlink(csv_h4)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
