"""Test para verificar que no hay colisiones en IDs de señales (7.1)"""
import pytest
from datetime import datetime, timezone
from kernel.contrato import Señal

def test_id_unico_diferente_direccion():
    """Dos señales mismo tiempo/estrategia pero distinta dirección deben tener ID diferente."""
    tiempo = datetime(2024, 6, 15, 10, 30, tzinfo=timezone.utc)
    
    senal_long = Señal(
        estrategia="PIVOT",
        simbolo="EURUSD",
        direccion=1,
        precio=1.0850,
        tiempo=tiempo,
        confianza=(70, 80),
        contexto={"detectores": ["D2_sweep", "D5_mss"]}
    )
    
    senal_short = Señal(
        estrategia="PIVOT",
        simbolo="EURUSD",
        direccion=-1,
        precio=1.0850,
        tiempo=tiempo,
        confianza=(70, 80),
        contexto={"detectores": ["D2_sweep", "D5_mss"]}
    )
    
    assert senal_long.id_señal != senal_short.id_señal, f"IDs deben ser diferentes por dirección: {senal_long.id_señal} vs {senal_short.id_señal}"

def test_id_unico_diferentes_detectores():
    """Dos señales mismo tiempo/dirección pero distintos detectores deben tener ID diferente."""
    tiempo = datetime(2024, 6, 15, 10, 30, tzinfo=timezone.utc)
    
    senal_a = Señal(
        estrategia="PIVOT",
        simbolo="EURUSD",
        direccion=1,
        precio=1.0850,
        tiempo=tiempo,
        confianza=(70, 80),
        contexto={"detectores": ["D2_sweep"]}
    )
    
    senal_b = Señal(
        estrategia="PIVOT",
        simbolo="EURUSD",
        direccion=1,
        precio=1.0850,
        tiempo=tiempo,
        confianza=(75, 85),
        contexto={"detectores": ["D2_sweep", "D5_mss"]}
    )
    
    assert senal_a.id_señal != senal_b.id_señal, f"IDs deben ser diferentes por detectores: {senal_a.id_señal} vs {senal_b.id_señal}"

def test_id_mismos_parametros_iguales():
    """Mismos parámetros exactos deben generar mismo ID (determinístico)."""
    tiempo = datetime(2024, 6, 15, 10, 30, tzinfo=timezone.utc)
    
    senal_1 = Señal(
        estrategia="PIVOT",
        simbolo="EURUSD",
        direccion=1,
        precio=1.0850,
        tiempo=tiempo,
        confianza=(70, 80),
        contexto={"detectores": ["D2_sweep", "D5_mss"]}
    )
    
    senal_2 = Señal(
        estrategia="PIVOT",
        simbolo="EURUSD",
        direccion=1,
        precio=1.0850,
        tiempo=tiempo,
        confianza=(90, 95),
        contexto={"detectores": ["D2_sweep", "D5_mss"]}
    )
    
    # El ID NO incluye confianza, solo detectores+direccion+tiempo
    assert senal_1.id_señal == senal_2.id_señal, f"IDs iguales si detectores/direccion/tiempo son iguales: {senal_1.id_señal}"
