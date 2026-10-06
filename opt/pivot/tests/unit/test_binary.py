# -*- coding: utf-8 -*-
"""Tests unitarios para módulo binary."""
import pytest
from datetime import datetime, date, timedelta, timezone
from kernel.binary.payout import get_payout_table, get_best_payout, PAYOUTS_DERIV
from kernel.binary.risk import (
    BinaryRiskMode, BinaryRiskConfig, BinaryRiskManager, TradeState,
    calculate_expected_value, calculate_breakeven_winrate, calculate_required_winrate_for_roi
)
from kernel.contrato import BinarySeñal, BinaryActivoInfo, BinaryRiskConfig as ContratoBinaryRiskConfig


class TestPayoutTables:
    """Tests para tablas de payout."""
    
    def test_deriv_eurusd_payouts(self):
        table = get_payout_table("deriv", "EURUSD")
        assert table.broker == "deriv"
        assert table.simbolo == "EURUSD"
        assert table.get(15) == 0.85
        assert table.get(60) == 0.87
    
    def test_fallback_to_generic(self):
        table = get_payout_table("deriv", "NONEXISTENT")
        # Debe caer en generic DEFAULT
        assert table.get(15) > 0
    
    def test_get_best_payout(self):
        broker, payout = get_best_payout("EURUSD", 15)
        assert broker in ("deriv", "iqoption", "pocket", "quotex")
        assert payout >= 0.85
    
    def test_breakeven_winrate(self):
        from kernel.binary.risk import calculate_breakeven_winrate
        # Payout 80% -> breakeven = 1/(1+0.8) = 55.56%
        be = calculate_breakeven_winrate(0.80)
        assert abs(be - 0.5555) < 0.01
    
    def test_required_winrate_for_roi(self):
        from kernel.binary.risk import calculate_required_winrate_for_roi
        # ROI 10% con payout 80%
        wr = calculate_required_winrate_for_roi(0.80, 0.10)
        assert wr > 0.55


class TestBinaryRiskManager:
    """Tests para BinaryRiskManager."""
    
    def setup_method(self):
        self.config = BinaryRiskConfig(
            mode=BinaryRiskMode.FIXED,
            fixed_amount=10.0,
            max_daily_loss_pct=0.05,
            max_daily_trades=20,
        )
        self.manager = BinaryRiskManager(self.config, capital_inicial=10000.0)
    
    def test_fixed_mode(self):
        amount = self.manager.calculate_next_amount(payout=0.80)
        assert amount == 10.0
    
    def test_martingale_mode(self):
        self.config.mode = BinaryRiskMode.MARTINGALE
        self.config.martingale_multiplier = 2.0
        self.manager = BinaryRiskManager(self.config, 10000.0)
        
        # Primera operación
        assert self.manager.calculate_next_amount(0.80) == 10.0
        
        # Simular pérdida
        self.manager.record_trade(-10.0, 10.0, False, date.today())
        
        # Segunda operación debe doblar
        assert self.manager.calculate_next_amount(0.80) == 20.0
        
        # Tercera pérdida
        self.manager.record_trade(-20.0, 20.0, False, date.today())
        assert self.manager.calculate_next_amount(0.80) == 40.0
        
        # Ganar resetea
        self.manager.record_trade(40.0 * 0.80, 40.0, True, date.today())
        assert self.manager.calculate_next_amount(0.80) == 10.0
    
    def test_anti_martingale_mode(self):
        self.config.mode = BinaryRiskMode.ANTI_MARTINGALE
        self.config.anti_martingale_multiplier = 1.5
        self.manager = BinaryRiskManager(self.config, 10000.0)
        
        # Ganar aumenta
        self.manager.record_trade(8.0, 10.0, True, date.today())
        assert self.manager.calculate_next_amount(0.80) == 15.0
        
        self.manager.record_trade(12.0, 15.0, True, date.today())
        assert self.manager.calculate_next_amount(0.80) == 22.5
        
        # Perder resetea
        self.manager.record_trade(-22.5, 22.5, False, date.today())
        assert self.manager.calculate_next_amount(0.80) == 10.0
    
    def test_percentage_mode(self):
        self.config.mode = BinaryRiskMode.PERCENTAGE
        self.config.percentage_of_capital = 0.02  # 2%
        self.manager = BinaryRiskManager(self.config, 10000.0)
        
        amount = self.manager.calculate_next_amount(0.80)
        assert amount == 200.0  # 2% de 10000
        
        # Capital cambia
        self.manager.update_capital(12000.0)
        amount = self.manager.calculate_next_amount(0.80)
        assert amount == 240.0  # 2% de 12000
    
    def test_kelly_mode(self):
        self.config.mode = BinaryRiskMode.KELLY
        self.config.kelly_fraction = 0.25
        self.config.kelly_min_winrate = 0.50
        self.manager = BinaryRiskManager(self.config, 10000.0)
        
        # Winrate 55%, payout 80% -> Kelly positivo
        amount = self.manager.calculate_next_amount(payout=0.80, winrate_estimate=0.55)
        assert amount > 0
        assert amount <= 1000.0  # Max 10% capital
        
        # Winrate bajo -> fallback a fixed
        self.config.kelly_min_winrate = 0.60
        self.manager = BinaryRiskManager(self.config, 10000.0)
        amount = self.manager.calculate_next_amount(payout=0.80, winrate_estimate=0.55)
        assert amount == 10.0
    
    def test_daily_limits(self):
        self.config.max_daily_trades = 2
        self.config.max_daily_loss_pct = 0.01  # 1%
        self.manager = BinaryRiskManager(self.config, 10000.0)
        
        # Primera operación
        assert self.manager.can_trade()
        self.manager.record_trade(-50.0, 10.0, False, date.today())
        
        # Segunda operación
        assert self.manager.can_trade()
        self.manager.record_trade(-60.0, 10.0, False, date.today())
        
        # Tercera operación bloqueada por max_daily_trades
        assert not self.manager.can_trade()
        
        # Test límite de pérdida diaria
        self.manager2 = BinaryRiskManager(
            BinaryRiskConfig(max_daily_loss_pct=0.005, max_daily_trades=10), 10000.0
        )
        self.manager2.record_trade(-60.0, 10.0, False, date.today())  # 0.6% loss
        assert not self.manager2.can_trade()  # Superó 0.5%
    
    def test_max_exposure(self):
        self.config.max_total_exposure_pct = 0.05  # 5%
        self.manager = BinaryRiskManager(self.config, 10000.0)
        
        # Amount mayor a 5% capital debería ser capado
        self.config.fixed_amount = 1000.0  # 10% capital
        self.manager = BinaryRiskManager(self.config, 10000.0)
        amount = self.manager.calculate_next_amount(0.80)
        assert amount == 500.0  # Capado a 5%


class TestBinarySeñal:
    """Tests para BinarySeñal."""
    
    def test_creacion_basica(self):
        sig = BinarySeñal(
            estrategia="test",
            simbolo="EURUSD",
            direccion=1,
            precio=1.0800,
            tiempo=datetime.now(timezone.utc),
            expiry_minutes=15,
            payout_pct=0.82,
        )
        
        assert sig.option_type == "CALL"
        assert sig.direccion == 1
        assert sig.expiry_minutes == 15
        assert sig.payout_pct == 0.82
        assert sig.expiry_timestamp is not None
    
    def test_put_direction(self):
        sig = BinarySeñal(
            estrategia="test",
            simbolo="EURUSD",
            direccion=-1,
            precio=1.0800,
            tiempo=datetime.now(timezone.utc),
        )
        assert sig.option_type == "PUT"
    
    def test_expiry_calculation(self):
        now = datetime.now(timezone.utc)
        sig = BinarySeñal(
            estrategia="test",
            simbolo="EURUSD",
            direccion=1,
            precio=1.0800,
            tiempo=now,
            expiry_minutes=30,
        )
        expected = now + timedelta(minutes=30)
        assert abs((sig.expiry_timestamp - expected).total_seconds()) < 1


class TestBinaryActivoInfo:
    """Tests para BinaryActivoInfo."""
    
    def test_payout_lookup(self):
        activo = BinaryActivoInfo(
            simbolo="EURUSD",
            punto=0.00001,
            tick_size=0.00001,
            payout_table={"15": 0.85, "60": 0.88},
        )
        
        assert activo.get_payout(15) == 0.85
        assert activo.get_payout(60) == 0.88
        # Fallback para valor no existente
        assert activo.get_payout(30) == 0.88  # El más cercano >= 30


class TestBinaryRiskConfig:
    """Tests para configuración de riesgo."""
    
    def test_default_config(self):
        config = BinaryRiskConfig()
        assert config.mode == BinaryRiskMode.FIXED
        assert config.fixed_amount == 10.0
    
    def test_custom_config(self):
        config = BinaryRiskConfig(
            mode=BinaryRiskMode.MARTINGALE,
            fixed_amount=20.0,
            martingale_multiplier=2.5,
            martingale_max_steps=3,
        )
        assert config.mode == BinaryRiskMode.MARTINGALE
        assert config.martingale_multiplier == 2.5


class TestExpectedValue:
    """Tests para cálculos de valor esperado."""
    
    def test_ev_positive(self):
        # Winrate 60%, payout 80%, amount $10
        ev = calculate_expected_value(payout=0.80, winrate=0.60, amount=10.0)
        # 0.6 * 10 * 0.8 - 0.4 * 10 = 4.8 - 4.0 = 0.8
        assert abs(ev - 0.8) < 0.01
    
    def test_ev_negative(self):
        # Winrate 50%, payout 70% -> EV negativo
        ev = calculate_expected_value(payout=0.70, winrate=0.50, amount=10.0)
        # 0.5 * 10 * 0.7 - 0.5 * 10 = 3.5 - 5.0 = -1.5
        assert ev < 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])