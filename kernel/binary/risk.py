# -*- coding: utf-8 -*-
"""
Gestión de riesgo para opciones binarias.
Implementa múltiples modos: fijo, martingala, anti-martingala, Kelly, porcentaje.
"""
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, date
import math


class BinaryRiskMode(str, Enum):
    FIXED = "fixed"
    MARTINGALE = "martingale"
    ANTI_MARTINGALE = "anti_martingale"
    KELLY = "kelly"
    PERCENTAGE = "percentage"


@dataclass
class BinaryRiskConfig:
    """Configuración de riesgo para binarias."""
    mode: BinaryRiskMode = BinaryRiskMode.FIXED
    
    # Fixed
    fixed_amount: float = 10.0
    
    # Martingala
    martingale_multiplier: float = 2.0
    martingale_max_steps: int = 4
    martingale_reset_on_win: bool = True
    
    # Anti-martingala
    anti_martingale_multiplier: float = 1.5
    anti_martingale_max_steps: int = 3
    
    # Kelly
    kelly_fraction: float = 0.25  # 25% de Kelly óptimo (conservador)
    kelly_min_winrate: float = 0.55
    kelly_min_payout: float = 0.70
    
    # Percentage
    percentage_of_capital: float = 0.02  # 2%
    
    # Límites globales
    max_daily_loss_pct: float = 0.05  # 5% pérdida diaria máxima
    max_daily_trades: int = 20
    max_concurrent_trades: int = 1
    max_total_exposure_pct: float = 0.10  # 10% capital en riesgo simultáneo
    
    # Configuración de símbolo (se sobreescribe desde ActivoInfo)
    min_contract: float = 1.0
    max_contract: float = 10000.0
    min_contracts_per_trade: int = 1
    max_contracts_per_trade: int = 100


@dataclass
class TradeState:
    """Estado actual para cálculo de siguiente tamaño."""
    consecutive_losses: int = 0
    consecutive_wins: int = 0
    current_step: int = 0  # Paso actual en martingala/anti-martingala
    base_amount: float = 10.0
    daily_loss: float = 0.0
    daily_trades: int = 0
    last_trade_date: Optional[date] = None
    last_was_win: bool = False
    
    def reset_daily(self, today: date):
        if self.last_trade_date != today:
            self.daily_loss = 0.0
            self.daily_trades = 0
            self.last_trade_date = today


class BinaryRiskManager:
    """
    Gestor de riesgo para opciones binarias.
    Calcula tamaño de posición según modo y estado actual.
    """
    
    def __init__(self, config: BinaryRiskConfig, capital_inicial: float):
        self.config = config
        self.capital_inicial = capital_inicial
        self.capital_actual = capital_inicial
        self.state = TradeState(base_amount=config.fixed_amount)
        self.trade_history: List[Dict[str, Any]] = []
    
    def update_capital(self, capital: float):
        """Actualiza capital actual (para Kelly y Percentage)."""
        self.capital_actual = capital
    
    def record_trade(self, pnl: float, contract_amount: float, is_win: bool, trade_date: date):
        """Registra resultado de operación para ajustar estado."""
        self.state.reset_daily(trade_date)
        self.state.daily_trades += 1
        
        if pnl < 0:
            self.state.daily_loss += abs(pnl)
            self.state.consecutive_losses += 1
            self.state.consecutive_wins = 0
            self.state.last_was_win = False
        else:
            self.state.consecutive_wins += 1
            self.state.consecutive_losses = 0
            self.state.last_was_win = True
        
        # Actualizar paso en martingala/anti-martingala
        if self.config.mode == BinaryRiskMode.MARTINGALE:
            if is_win:
                if self.config.martingale_reset_on_win:
                    self.state.current_step = 0
            else:
                self.state.current_step = min(
                    self.state.current_step + 1, 
                    self.config.martingale_max_steps
                )
        elif self.config.mode == BinaryRiskMode.ANTI_MARTINGALE:
            if is_win:
                self.state.current_step = min(
                    self.state.current_step + 1,
                    self.config.anti_martingale_max_steps
                )
            else:
                self.state.current_step = 0
        
        self.trade_history.append({
            "date": trade_date.isoformat(),
            "pnl": pnl,
            "amount": contract_amount,
            "win": is_win,
            "step": self.state.current_step,
        })
    
    def calculate_next_amount(self, payout: float, winrate_estimate: float = 0.55) -> float:
        """
        Calcula el monto para la próxima operación.
        
        Args:
            payout: Payout decimal (ej: 0.82)
            winrate_estimate: Winrate estimado para Kelly (default 55%)
        
        Returns:
            Monto en USD para próximo contrato (redondeado a 2 decimales)
        """
        today = date.today()
        self.state.reset_daily(today)
        
        # Verificar límites diarios
        if self.state.daily_trades >= self.config.max_daily_trades:
            return 0.0
        
        if self.state.daily_loss >= self.capital_actual * self.config.max_daily_loss_pct:
            return 0.0
        
        # Calcular según modo
        if self.config.mode == BinaryRiskMode.FIXED:
            amount = self.config.fixed_amount
        
        elif self.config.mode == BinaryRiskMode.MARTINGALE:
            if self.state.current_step == 0:
                amount = self.config.fixed_amount
            else:
                amount = self.config.fixed_amount * (self.config.martingale_multiplier ** self.state.current_step)
        
        elif self.config.mode == BinaryRiskMode.ANTI_MARTINGALE:
            if self.state.current_step == 0:
                amount = self.config.fixed_amount
            else:
                amount = self.config.fixed_amount * (self.config.anti_martingale_multiplier ** self.state.current_step)
        
        elif self.config.mode == BinaryRiskMode.KELLY:
            amount = self._kelly_amount(payout, winrate_estimate)
        
        elif self.config.mode == BinaryRiskMode.PERCENTAGE:
            amount = self.capital_actual * self.config.percentage_of_capital
        
        else:
            amount = self.config.fixed_amount
        
        # Aplicar límites de contrato
        amount = max(self.config.min_contract, min(amount, self.config.max_contract))
        
        # Límite de exposición total
        max_exposure = self.capital_actual * self.config.max_total_exposure_pct
        if amount > max_exposure:
            amount = max_exposure
        
        return round(amount, 2)
    
    def _kelly_amount(self, payout: float, winrate: float) -> float:
        """
        Calcula Kelly óptimo fraccional para opciones binarias.
        
        Kelly% = (p * b - q) / b
        donde:
        - p = probabilidad de ganar (winrate)
        - q = 1 - p
        - b = payout (lo que ganas por cada 1 apostado)
        
        Para binarias: si apuestas $1 y ganas, recibes $1 * payout + $1 = $1 * (1+payout)
        Pero el riesgo es $1. El "b" en Kelly es payout.
        """
        if winrate < self.config.kelly_min_winrate:
            return self.config.fixed_amount
        
        if payout < self.config.kelly_min_payout:
            return self.config.fixed_amount
        
        p = winrate
        q = 1 - p
        b = payout  # ganancia neta por dólar apostado
        
        if b <= 0:
            return self.config.fixed_amount
        
        kelly_pct = (p * b - q) / b
        
        if kelly_pct <= 0:
            return self.config.fixed_amount
        
        # Aplicar fracción de Kelly (conservador)
        kelly_pct *= self.config.kelly_fraction
        
        # Limitar a máximo razonable
        kelly_pct = min(kelly_pct, 0.10)  # Max 10% capital por trade
        
        return self.capital_actual * kelly_pct
    
    def can_trade(self) -> bool:
        """Verifica si se puede operar según límites."""
        today = date.today()
        self.state.reset_daily(today)
        
        if self.state.daily_trades >= self.config.max_daily_trades:
            return False
        
        if self.state.daily_loss >= self.capital_actual * self.config.max_daily_loss_pct:
            return False
        
        return True
    
    def get_status(self) -> Dict[str, Any]:
        """Estado actual del risk manager."""
        today = date.today()
        self.state.reset_daily(today)
        
        return {
            "mode": self.config.mode.value,
            "capital_actual": round(self.capital_actual, 2),
            "daily_trades": self.state.daily_trades,
            "daily_loss": round(self.state.daily_loss, 2),
            "daily_loss_pct": round(self.state.daily_loss / self.capital_actual * 100, 2) if self.capital_actual > 0 else 0,
            "consecutive_losses": self.state.consecutive_losses,
            "consecutive_wins": self.state.consecutive_wins,
            "current_step": self.state.current_step,
            "next_amount_fixed": self.config.fixed_amount,
            "can_trade": self.can_trade(),
        }


def calculate_expected_value(payout: float, winrate: float, amount: float) -> float:
    """
    Calcula valor esperado de una operación binaria.
    
    EV = p * (amount * payout) - q * amount
    """
    p = winrate
    q = 1 - p
    return p * amount * payout - q * amount


def calculate_breakeven_winrate(payout: float) -> float:
    """Calcula winrate mínimo para break-even."""
    return 1 / (1 + payout)


def calculate_required_winrate_for_roi(payout: float, target_roi: float) -> float:
    """
    Winrate necesario para lograr un ROI objetivo.
    ROI = (p * payout - q) = p * (1 + payout) - 1
    """
    return (1 + target_roi) / (1 + payout)