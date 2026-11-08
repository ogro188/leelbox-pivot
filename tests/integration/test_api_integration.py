"""
Tests de integración para la API REST.
Verifica endpoints completos con datos reales.
"""
import pytest
from fastapi.testclient import TestClient
from kernel.api.app import create_app
from datetime import datetime


@pytest.fixture
def client():
    """Fixture que crea un cliente de test para la API."""
    app = create_app()
    with TestClient(app) as client:
        yield client


class TestAPIAssets:
    """Tests para endpoint /api/assets."""
    
    def test_get_assets_returns_list(self, client):
        """Verifica que GET /api/assets retorna lista no vacía."""
        response = client.get("/api/assets")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
    
    def test_assets_have_required_fields(self, client):
        """Verifica que cada activo tiene campos requeridos."""
        response = client.get("/api/assets")
        data = response.json()
        
        for asset in data:
            assert "simbolo" in asset
            assert "punto" in asset
            assert "activo" in asset
            assert asset["activo"] is True
    
    def test_eurusd_in_assets(self, client):
        """Verifica que EURUSD está en la lista de activos."""
        response = client.get("/api/assets")
        data = response.json()
        simbolos = [a["simbolo"] for a in data]
        assert "EURUSD" in simbolos


class TestAPIStrategies:
    """Tests para endpoint /api/strategies."""
    
    def test_get_strategies_returns_list(self, client):
        """Verifica que GET /api/strategies retorna lista no vacía."""
        response = client.get("/api/strategies")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
    
    def test_strategies_have_required_fields(self, client):
        """Verifica que cada estrategia tiene campos requeridos."""
        response = client.get("/api/strategies")
        data = response.json()
        
        for strategy in data:
            assert "nombre" in strategy
            assert "descripcion" in strategy or "parametros" in strategy
    
    def test_pivot_strategy_exists(self, client):
        """Verifica que la estrategia PIVOT está disponible."""
        response = client.get("/api/strategies")
        data = response.json()
        nombres = [s["nombre"] for s in data]
        assert "PIVOT" in nombres


class TestAPIBacktest:
    """Tests para endpoint POST /api/backtest."""
    
    def test_backtest_with_valid_request(self, client):
        """Verifica backtest con request válido."""
        request_data = {
            "estrategia": "PIVOT",
            "activo": "EURUSD",
            "timeframe": "M15",
            "fecha_inicio": "2024-01-01",
            "fecha_fin": "2024-12-31",
            "capital_inicial": 10000,
            "riesgo_por_operacion": 0.01
        }
        
        response = client.post("/api/backtest", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        # Verificar campos de respuesta
        assert data["status"] == "completed"
        assert data["estrategia"] == "PIVOT"
        assert data["activo"] == "EURUSD"
        assert "total_operaciones" in data
        assert "winrate" in data
    
    def test_backtest_rejects_missing_fields(self, client):
        """Verifica que backtest rechaza requests incompletos."""
        request_data = {
            "estrategia": "PIVOT",
            # Faltan campos requeridos
        }
        
        response = client.post("/api/backtest", json=request_data)
        assert response.status_code == 400
        assert "Campo requerido faltante" in response.json()["detail"]
    
    def test_backtest_rejects_invalid_strategy(self, client):
        """Verifica que backtest rechaza estrategia inexistente."""
        request_data = {
            "estrategia": "NOEXISTE",
            "activo": "EURUSD",
            "timeframe": "M15",
            "fecha_inicio": "2024-01-01",
            "fecha_fin": "2024-12-31"
        }
        
        response = client.post("/api/backtest", json=request_data)
        assert response.status_code == 404
        assert "no encontrada" in response.json()["detail"]
    
    def test_backtest_rejects_invalid_asset(self, client):
        """Verifica que backtest rechaza activo inexistente."""
        request_data = {
            "estrategia": "PIVOT",
            "activo": "NOEXISTE",
            "timeframe": "M15",
            "fecha_inicio": "2024-01-01",
            "fecha_fin": "2024-12-31"
        }
        
        response = client.post("/api/backtest", json=request_data)
        assert response.status_code == 404
    
    def test_backtest_rejects_invalid_date_format(self, client):
        """Verifica que backtest rechaza formato de fecha inválido."""
        request_data = {
            "estrategia": "PIVOT",
            "activo": "EURUSD",
            "timeframe": "M15",
            "fecha_inicio": "01-01-2024",  # Formato incorrecto
            "fecha_fin": "2024-12-31"
        }
        
        response = client.post("/api/backtest", json=request_data)
        assert response.status_code == 400
        assert "Formato de fecha inválido" in response.json()["detail"]
    
    def test_backtest_uses_real_engine_not_mock(self, client):
        """Verifica que el backtest usa motor real, no mock."""
        request_data = {
            "estrategia": "PIVOT",
            "activo": "EURUSD",
            "timeframe": "M15",
            "fecha_inicio": "2024-01-01",
            "fecha_fin": "2024-12-31"
        }
        
        response = client.post("/api/backtest", json=request_data)
        assert response.status_code == 200
        data = response.json()
        
        # El mock retornaba mensaje específico
        assert "mensaje" not in data or "en implementación" not in data.get("mensaje", "")
        
        # Debe tener métricas reales (aunque sean 0 operaciones)
        assert "total_operaciones" in data
        assert "winrate" in data


class TestAPICSVFeedFilter:
    """Tests para filtro de fechas en CSVFeed usado por API."""
    
    def test_csv_feed_filters_by_date_range(self):
        """Verifica que CSVFeed filtra correctamente por rango de fechas."""
        from kernel.feeds.csv import CSVFeed
        
        # Sin filtro
        feed_full = CSVFeed(
            path="data/eurusd_m15.csv",
            timeframe="M15",
            symbol="EURUSD"
        )
        total_velas = len(feed_full.df)
        
        # Con filtro estrecho (ajustado al rango real de datos: 1-3 de Enero 2024)
        feed_filtered = CSVFeed(
            path="data/eurusd_m15.csv",
            timeframe="M15",
            symbol="EURUSD",
            fecha_inicio=datetime(2024, 1, 1),
            fecha_fin=datetime(2024, 1, 3)
        )
        filtered_velas = len(feed_filtered.df)
        
        assert filtered_velas < total_velas
        assert filtered_velas > 0
        
        # Verificar que las fechas están dentro del rango
        primera_fecha = feed_filtered.df.index[0]
        ultima_fecha = feed_filtered.df.index[-1]
        assert primera_fecha >= datetime(2024, 1, 1).replace(tzinfo=feed_filtered.tz)
        assert ultima_fecha <= datetime(2024, 1, 3).replace(tzinfo=feed_filtered.tz)
