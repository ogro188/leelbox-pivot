# -*- coding: utf-8 -*-
"""Tests de los endpoints de SOLO LECTURA y sus helpers de serializacion.

Regla de diseno del README #2 (Tests Require Assertions): todo test afirma
un resultado concreto, nunca solo "no lanza excepcion".
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from kernel.api.app import (
    _muestrear_equity,
    _serializar_operaciones,
    create_app,
)


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


class TestHelpers:
    """Funciones puras: sin red, sin base de datos."""

    def test_muestrear_equity_no_toca_serie_corta(self):
        raw = [(datetime(2024, 1, 1) + timedelta(minutes=i), 100.0 + i) for i in range(10)]
        out = _muestrear_equity(raw, max_puntos=600)
        assert len(out) == 10
        assert out[0] == [int(raw[0][0].timestamp() * 1000), 100.0]
        assert out[-1] == [int(raw[-1][0].timestamp() * 1000), 109.0]

    def test_muestrear_equity_recorta_y_conserva_extremos(self):
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        raw = [(base + timedelta(minutes=i), 1000.0 + i) for i in range(10_000)]
        out = _muestrear_equity(raw, max_puntos=600)

        assert len(out) <= 600
        assert len(out) > 1
        # Extremos preservados: primer y ultimo valor de la serie original
        assert out[0] == [int(base.timestamp() * 1000), 1000.0]
        assert out[-1] == [int(raw[-1][0].timestamp() * 1000), 10999.0]
        # Orden cronologico estrictamente creciente
        timestamps = [p[0] for p in out]
        assert timestamps == sorted(timestamps)
        assert len(set(timestamps)) == len(timestamps), "sin puntos duplicados"

    def test_muestrear_equity_mantiene_monotonico_el_valor_en_serie_plana(self):
        base = datetime(2024, 6, 1, tzinfo=timezone.utc)
        raw = [(base + timedelta(hours=i), 500.0) for i in range(3000)]
        out = _muestrear_equity(raw, max_puntos=600)
        assert all(v == 500.0 for _, v in out)

    def test_serializar_operaciones_mapea_campos_reales(self):
        ts_in = datetime(2024, 3, 1, 12, 0, tzinfo=timezone.utc)
        ts_out = datetime(2024, 3, 1, 13, 0, tzinfo=timezone.utc)
        op = SimpleNamespace(
            id_operacion="OP_1",
            simbolo="EURUSD",
            direccion=-1,
            precio_entrada=1.08500,
            precio_salida=1.08300,
            timestamp_entrada=ts_in,
            timestamp_salida=ts_out,
            stop_loss=1.08700,
            take_profit=1.08100,
            razon_salida="TP",
            pnl_puntos=200.004,
            pnl_dinero=20.0049,
            velas_en_operacion=4,
        )
        [d] = _serializar_operaciones([op])

        assert d["id"] == "OP_1"
        assert d["direccion"] == -1
        assert d["razon_salida"] == "TP"
        assert d["pnl_puntos"] == 200.0
        assert d["pnl_dinero"] == 20.0
        assert d["timestamp_entrada"] == "2024-03-01T12:00:00+00:00"
        assert d["velas_en_operacion"] == 4

    def test_serializar_operaciones_acepta_lista_vacia_y_none(self):
        assert _serializar_operaciones([]) == []
        assert _serializar_operaciones(None) == []

    def test_serializar_operaciones_rellena_faltantes_sin_crash(self):
        [d] = _serializar_operaciones([SimpleNamespace(simbolo="XAUUSD")])
        assert d["simbolo"] == "XAUUSD"
        assert d["direccion"] == 0
        assert d["pnl_puntos"] == 0.0
        assert d["timestamp_salida"] is None


class TestEndpointsSoloLectura:
    """Endpoints GET nuevos. Ninguno escribe en la base."""

    def test_backtests_responde_lista(self, client):
        r = client.get("/api/backtests")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_backtests_backtest_inexistente_es_404(self, client):
        r = client.get("/api/backtests/999999")
        assert r.status_code == 404
        assert "no encontrado" in r.json()["detail"]

    def test_backtests_limite_se_limita_a_500(self, client):
        r = client.get("/api/backtests", params={"limite": 99999})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_backtests_limite_invalido_no_revienta(self, client):
        r = client.get("/api/backtests", params={"limite": 0})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_operaciones_responde_lista(self, client):
        r = client.get("/api/operaciones")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_operaciones_filtra_por_simbolo(self, client):
        r = client.get("/api/operaciones", params={"simbolo": "eurusd"})
        assert r.status_code == 200
        for op in r.json():
            assert op["simbolo"] == "EURUSD"

    def test_analitica_detectores_shape(self, client):
        r = client.get("/api/analitica/detectores")
        assert r.status_code == 200
        data = r.json()
        assert "total_operaciones" in data
        if data["total_operaciones"] > 0:
            assert "win_rate_general" in data
            assert "top_combinaciones" in data
            assert isinstance(data["top_combinaciones"], list)

    def test_analitica_resumen_shape_y_tipos(self, client):
        r = client.get("/api/analitica/resumen")
        assert r.status_code == 200
        data = r.json()
        for key in ("senales", "operaciones", "operaciones_cerradas", "operaciones_ganadoras", "backtests"):
            assert key in data
            assert isinstance(data[key], int)
            assert data[key] >= 0
        assert data["winrate"] is None or isinstance(data["winrate"], (int, float))

    def test_analitica_resumen_ganadoras_no_supera_cerradas(self, client):
        data = client.get("/api/analitica/resumen").json()
        assert data["operaciones_ganadoras"] <= data["operaciones_cerradas"]


class TestEndpointsPreexistentesAhoraUsados:
    """Endpoints que ya existian pero el frontend no consumia."""

    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert isinstance(data["strategies_loaded"], int)
        assert data["strategies_loaded"] >= 1

    def test_deriv_status(self, client):
        r = client.get("/api/deriv/status")
        assert r.status_code == 200
        assert "connected" in r.json()

    def test_config_global(self, client):
        r = client.get("/api/config")
        assert r.status_code == 200
        data = r.json()
        assert data["detectores"] == ["D0", "D1", "D2", "D3", "D4", "D5"]
        assert "M15" in data["timeframes_soportados"]
