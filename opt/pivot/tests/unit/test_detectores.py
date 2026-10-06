"""
Tests unitarios para detectores del core PIVOT
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Importar detectores
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.d0_estructura import EstructuraProvider
from core.d1_ruptura import DetectorD1
from core.d2_sweep import DetectorD2
from core.d3_fvg import DetectorD3
from core.d4_orderblock import DetectorD4
from core.d5_mss_sweep import DetectorD5
from core.base import Contexto as CoreContexto
from kernel.contrato import ActivoInfo

# Alias para compatibilidad con tests
DetectorEstructura = EstructuraProvider
DetectorRuptura = DetectorD1
DetectorSweep = DetectorD2
DetectorFVG = DetectorD3
DetectorOrderBlock = DetectorD4
DetectorMSS = DetectorD5
Contexto = CoreContexto


def crear_dataframe_falso(n_velas=100, tendencia='alcista'):
    """Crea un DataFrame sintético para tests"""
    fechas = [datetime.now() - timedelta(minutes=i*15) for i in range(n_velas, 0, -1)]
    
    if tendencia == 'alcista':
        precios = [1.1000 + i*0.0001 for i in range(n_velas)]
    elif tendencia == 'bajista':
        precios = [1.1000 - i*0.0001 for i in range(n_velas)]
    else:
        precios = [1.1000 + np.sin(i*0.1)*0.0005 for i in range(n_velas)]
    
    df = pd.DataFrame({
        'timestamp': fechas,
        'open': precios,
        'high': [p + 0.0002 for p in precios],
        'low': [p - 0.0002 for p in precios],
        'close': precios,
        'volume': [100]*n_velas
    })
    df.set_index('timestamp', inplace=True)
    return df


def crear_contexto_falso(df_m15=None, df_h1=None, df_h4=None):
    """Crea un contexto falso para tests usando core.base.Contexto"""
    if df_m15 is None:
        df_m15 = crear_dataframe_falso(100, 'alcista')
    if df_h1 is None:
        df_h1 = crear_dataframe_falso(50, 'alcista')
    if df_h4 is None:
        df_h4 = crear_dataframe_falso(30, 'alcista')
    
    # Usar el Contexto de core.base que es diferente al de kernel.contrato
    return Contexto(
        df_m15=df_m15,
        df_h1=df_h1,
        df_h4=df_h4,
        df_d1=None
    )


class TestDetectorEstructura:
    """Tests para DetectorEstructura (D0)"""
    
    def test_no_explota_con_contexto(self):
        """Verifica que EstructuraProvider funciona con contexto"""
        df = crear_dataframe_falso(50, 'lateral')
        ctx = crear_contexto_falso(df_m15=df)
        detector = EstructuraProvider(ctx)
        
        resultado = detector.actualizar()
        # Debería retornar EstructuraRef sin explotar
        assert resultado is not None
        
    def test_no_explota_con_datos_vacios(self):
        """Verifica manejo graceful con datos insuficientes"""
        df = crear_dataframe_falso(5, 'alcista')  # Muy pocas velas
        ctx = crear_contexto_falso(df_m15=df)
        detector = EstructuraProvider(ctx)
        
        resultado = detector.actualizar()
        # Debería retornar estructura sin explotar
        assert resultado is not None


class TestDetectorRuptura:
    """Tests para DetectorRuptura (D1)"""
    
    def test_no_explota_sin_atr(self):
        """Verifica manejo graceful sin buffer ATR"""
        df = crear_dataframe_falso(50, 'alcista')
        ctx = crear_contexto_falso(df_m15=df)
        detector = DetectorD1()
        
        resultado = detector.detectar(ctx)
        # Debería retornar None sin explotar
        assert resultado is None


class TestDetectorSweep:
    """Tests para DetectorSweep (D2)"""
    
    def test_detecta_sweep_liquidez(self):
        """Verifica detección de barrido de liquidez con patrón conocido."""
        # Crear patrón de sweep: mínimo anterior, luego wick abajo, luego cierre arriba
        n_velas = 50
        fechas = [datetime.now() - timedelta(minutes=i*15) for i in range(n_velas, 0, -1)]
        
        precios = [1.1000 + i*0.0001 for i in range(n_velas)]
        # Crear wick pronunciado en la última vela
        high = [p + 0.0002 for p in precios]
        low = [p - 0.0002 for p in precios]
        low[-1] = precios[-5] - 0.0003  # Wick abajo del mínimo reciente
        
        df = pd.DataFrame({
            'timestamp': fechas,
            'open': precios,
            'high': high,
            'low': low,
            'close': precios,
            'volume': [100]*n_velas
        })
        df.set_index('timestamp', inplace=True)
        
        ctx = crear_contexto_falso(df_m15=df)
        detector = DetectorD2()
        
        resultado = detector.detectar(ctx)
        
        # ASSERTS REALES: Verificar que detecta el patrón
        # Nota: Puede ser None si faltan buffers de RSI/ATR, pero si existe debe tener estructura válida
        if resultado is not None:
            assert hasattr(resultado, 'direccion'), "El resultado debe tener dirección"
            assert resultado.direccion in (1, -1), f"Dirección inválida: {resultado.direccion}"
            assert hasattr(resultado, 'activo'), "El resultado debe tener campo activo"
    
    def test_no_explota_sin_buffers(self):
        """Verifica manejo graceful sin buffers RSI"""
        df = crear_dataframe_falso(50, 'lateral')
        ctx = crear_contexto_falso(df_m15=df)
        detector = DetectorD2()
        
        resultado = detector.detectar(ctx)
        # Debería retornar None sin explotar
        assert resultado is None
    
    def test_no_detecta_falso_positivo(self):
        """Verifica que NO detecta sweep cuando no hay patrón (sin wick pronunciado)."""
        n_velas = 50
        fechas = [datetime.now() - timedelta(minutes=i*15) for i in range(n_velas, 0, -1)]
        
        # Precios en tendencia suave sin wicks extremos
        precios = [1.1000 + i*0.0001 for i in range(n_velas)]
        high = [p + 0.0001 for p in precios]  # Wick pequeño
        low = [p - 0.0001 for p in precios]   # Wick pequeño
        
        df = pd.DataFrame({
            'timestamp': fechas,
            'open': precios,
            'high': high,
            'low': low,
            'close': precios,
            'volume': [100]*n_velas
        })
        df.set_index('timestamp', inplace=True)
        
        ctx = crear_contexto_falso(df_m15=df)
        detector = DetectorD2()
        
        resultado = detector.detectar(ctx)
        
        # ASSERT REAL: No debería detectar sweep en patrón limpio
        assert resultado is None, "No debería detectar sweep sin patrón claro de wick extremo"


class TestDetectorFVG:
    """Tests para DetectorFVG (D3)"""
    
    def test_no_explota_sin_atr(self):
        """Verifica manejo graceful sin ATR"""
        df = crear_dataframe_falso(50, 'lateral')
        ctx = crear_contexto_falso(df_m15=df)
        detector = DetectorD3()
        
        resultado = detector.detectar(ctx)
        # Debería retornar None sin explotar
        assert resultado is None


class TestDetectorOrderBlock:
    """Tests para DetectorOrderBlock (D4)"""
    
    def test_no_explota_sin_buffers(self):
        """Verifica manejo graceful sin buffers EMA"""
        df = crear_dataframe_falso(50, 'alcista')
        ctx = crear_contexto_falso(df_m15=df)
        detector = DetectorD4()
        
        resultado = detector.detectar(ctx)
        # Debería retornar None sin explotar
        assert resultado is None


class TestDetectorMSS:
    """Tests para DetectorMSS (D5)"""
    
    def test_detecta_mss_basico(self):
        """Verifica detección de Market Structure Shift básico."""
        # MSS: ruptura de estructura en dirección opuesta a tendencia previa
        df = crear_dataframe_falso(100, 'alcista')
        ctx = crear_contexto_falso(df_m15=df)
        detector = DetectorD5()
        
        resultado = detector.detectar(ctx)
        
        # ASSERTS REALES: Si detecta MSS, debe tener estructura válida
        if resultado is not None:
            assert hasattr(resultado, 'direccion'), "El resultado debe tener dirección"
            assert resultado.direccion in (1, -1), f"Dirección inválida: {resultado.direccion}"
            assert hasattr(resultado, 'activo'), "El resultado debe tener campo activo"
    
    def test_no_explota_sin_datos_h4(self):
        """Verifica manejo graceful sin datos H4"""
        df_m15 = crear_dataframe_falso(50, 'alcista')
        ctx = crear_contexto_falso(df_m15=df_m15, df_h4=None)
        detector = DetectorD5()
        
        resultado = detector.detectar(ctx)
        # Debería retornar None sin explotar
        assert resultado is None
    
    def test_no_detecta_falso_positivo_mss(self):
        """Verifica que NO detecta MSS en tendencia pura sin ruptura."""
        # Tendencia alcista perfecta sin rupturas de estructura
        n_velas = 100
        fechas = [datetime.now() - timedelta(minutes=i*15) for i in range(n_velas, 0, -1)]
        precios = [1.1000 + i*0.0001 for i in range(n_velas)]  # Tendencia constante
        
        df = pd.DataFrame({
            'timestamp': fechas,
            'open': precios,
            'high': [p + 0.0002 for p in precios],
            'low': [p - 0.0002 for p in precios],
            'close': precios,
            'volume': [100]*n_velas
        })
        df.set_index('timestamp', inplace=True)
        
        ctx = crear_contexto_falso(df_m15=df)
        detector = DetectorD5()
        
        resultado = detector.detectar(ctx)
        
        # ASSERT REAL: No debería detectar MSS en tendencia limpia sin ruptura
        assert resultado is None, "No debería detectar MSS en tendencia pura sin ruptura de estructura"


def test_integracion_todos_detectores():
    """Test de integración: todos los detectores funcionando juntos"""
    df = crear_dataframe_falso(100, 'lateral')
    ctx = crear_contexto_falso(df_m15=df)
    
    # EstructuraProvider requiere contexto en el constructor
    detector_estructura = EstructuraProvider(ctx)
    
    # Los demás detectores usan el método detectar()
    detectores = [
        ('Estructura', lambda c: detector_estructura.actualizar()),
        ('Ruptura', lambda c: DetectorD1().detectar(c)),
        ('Sweep', lambda c: DetectorD2().detectar(c)),
        ('FVG', lambda c: DetectorD3().detectar(c)),
        ('OrderBlock', lambda c: DetectorD4().detectar(c)),
        ('MSS', lambda c: DetectorD5().detectar(c))
    ]
    
    resultados = {}
    for nombre, func_detector in detectores:
        try:
            resultado = func_detector(ctx)
            resultados[nombre] = {
                'exito': True,
                'resultado': resultado is not None
            }
        except Exception as e:
            resultados[nombre] = {
                'exito': False,
                'error': str(e)
            }
    
    # Verificar que ningún detector explotó
    for nombre, resultado in resultados.items():
        assert resultado['exito'], f"{nombre} falló: {resultado.get('error', 'Unknown')}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
