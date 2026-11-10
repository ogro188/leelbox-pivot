# -*- coding: utf-8 -*-
"""Coherencia temporal de la alerta: apertura, cierre y zona horaria."""
from datetime import datetime, timezone

from core.alertas import AlertasEngine
from core.estructuras import Signal


def _senal():
    sig = Signal()
    sig.symbol = "EURUSD"
    sig.detector = "D2"
    sig.direction = 1
    sig.entry_time = datetime(2026, 1, 5, 14, 0, tzinfo=timezone.utc)
    sig.entry_price = 1.23456
    sig.session = "NY"
    sig.kill_zone = "NONE"
    sig.hipotesis_causa = "causa"
    sig.hipotesis_efecto = "efecto"
    sig.hipotesis_razon = "razon"
    sig.hipotesis_invalidez = "invalidez"
    sig.hipotesis_expiry_velas = 1
    sig.hipotesis_expiry_minutos = 15
    sig.hipotesis_objetivo = 1.23500
    sig.hipotesis_prob_min = 50
    sig.hipotesis_prob_max = 60
    sig.conviccion = "MEDIA"
    sig.velocidad_aproximacion = 50
    sig.regimen_volatilidad = "NORMAL"
    return sig


def test_decision_time_es_el_cierre():
    sig = _senal()
    assert sig.entry_time.hour == 14 and sig.entry_time.minute == 0
    assert sig.decision_time.hour == 14 and sig.decision_time.minute == 15


def test_alerta_muestra_cierre_y_zona_utc():
    sig = _senal()
    texto = AlertasEngine(point=0.00001).build_alert_text(sig)
    assert "⚡ 14:15 UTC · NY" in texto
    assert "REFERENCIA: 1.23456 (cierre 14:15 UTC)" in texto
    assert "⚡ 14:00" not in texto


def test_meta_alerta_parsea_hora_y_sesion():
    sig = _senal()
    eng = AlertasEngine(point=0.00001)
    meta = eng._meta_alerta(eng.build_alert_text(sig))
    assert meta["hora"] == "14:15"
    assert meta["sesion"] == "NY"


def test_alerta_incluye_deriva_si_hay_precio_actual():
    sig = _senal()
    texto = AlertasEngine(point=0.00001).build_alert_text(
        sig, precio_actual=1.23460
    )
    assert "PRECIO AL ENVIAR: 1.23460" in texto
    assert "Deriva: +4.0 pts" in texto
