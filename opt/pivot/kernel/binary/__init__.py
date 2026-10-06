# -*- coding: utf-8 -*-
"""
Módulo Binary - Opciones Binarias
"""
from kernel.binary.payout import (
    PAYOUTS_DERIV, PAYOUTS_IQOPTION, PAYOUTS_POCKET, PAYOUTS_QUOTEX, PAYOUTS_GENERIC,
    ALL_BROKERS, PayoutTable, get_payout_table, get_available_symbols, get_best_payout
)
from kernel.binary.risk import (
    BinaryRiskMode, BinaryRiskConfig, BinaryRiskManager, TradeState,
    calculate_expected_value, calculate_breakeven_winrate, calculate_required_winrate_for_roi
)
from kernel.binary.engine import BinaryBacktestEngine, BinaryOperacion, run_binary_backtest

__all__ = [
    # Payouts
    "PAYOUTS_DERIV", "PAYOUTS_IQOPTION", "PAYOUTS_POCKET", "PAYOUTS_QUOTEX", "PAYOUTS_GENERIC",
    "ALL_BROKERS", "PayoutTable", "get_payout_table", "get_available_symbols", "get_best_payout",
    # Risk
    "BinaryRiskMode", "BinaryRiskConfig", "BinaryRiskManager", "TradeState",
    "calculate_expected_value", "calculate_breakeven_winrate", "calculate_required_winrate_for_roi",
    # Engine
    "BinaryBacktestEngine", "BinaryOperacion", "run_binary_backtest",
]