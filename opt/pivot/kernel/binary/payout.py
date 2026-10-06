# -*- coding: utf-8 -*-
"""
Tablas de payout para opciones binarias por broker, activo y horizonte.
Valores basados en ofertas públicas típicas (referencia 2024).
"""
from typing import Dict, Optional
from dataclasses import dataclass, field


# =============================================================================
# PAYOUTS POR BROKER (valores típicos, verificar en cada broker)
# =============================================================================

PAYOUTS_DERIV = {
    "EURUSD": {"1": 0.78, "5": 0.82, "10": 0.84, "15": 0.85, "30": 0.86, "60": 0.87, "EOD": 0.90},
    "GBPUSD": {"1": 0.77, "5": 0.81, "10": 0.83, "15": 0.84, "30": 0.85, "60": 0.86, "EOD": 0.89},
    "USDJPY": {"1": 0.78, "5": 0.82, "10": 0.84, "15": 0.85, "30": 0.86, "60": 0.87, "EOD": 0.90},
    "AUDUSD": {"1": 0.76, "5": 0.80, "10": 0.82, "15": 0.83, "30": 0.84, "60": 0.85, "EOD": 0.88},
    "USDCAD": {"1": 0.76, "5": 0.80, "10": 0.82, "15": 0.83, "30": 0.84, "60": 0.85, "EOD": 0.88},
    "NZDUSD": {"1": 0.75, "5": 0.79, "10": 0.81, "15": 0.82, "30": 0.83, "60": 0.84, "EOD": 0.87},
    "EURGBP": {"1": 0.75, "5": 0.79, "10": 0.81, "15": 0.82, "30": 0.83, "60": 0.84, "EOD": 0.87},
    "EURJPY": {"1": 0.77, "5": 0.81, "10": 0.83, "15": 0.84, "30": 0.85, "60": 0.86, "EOD": 0.89},
    "GBPJPY": {"1": 0.78, "5": 0.82, "10": 0.84, "15": 0.85, "30": 0.86, "60": 0.87, "EOD": 0.90},
    "XAUUSD": {"1": 0.74, "5": 0.78, "10": 0.80, "15": 0.81, "30": 0.82, "60": 0.83, "EOD": 0.86},
    "XAGUSD": {"1": 0.73, "5": 0.77, "10": 0.79, "15": 0.80, "30": 0.81, "60": 0.82, "EOD": 0.85},
    "BTCUSD": {"1": 0.70, "5": 0.74, "10": 0.76, "15": 0.77, "30": 0.78, "60": 0.79, "EOD": 0.82},
    "ETHUSD": {"1": 0.69, "5": 0.73, "10": 0.75, "15": 0.76, "30": 0.77, "60": 0.78, "EOD": 0.81},
    "US30":   {"1": 0.72, "5": 0.76, "10": 0.78, "15": 0.79, "30": 0.80, "60": 0.81, "EOD": 0.84},
    "US100":  {"1": 0.72, "5": 0.76, "10": 0.78, "15": 0.79, "30": 0.80, "60": 0.81, "EOD": 0.84},
    "US500":  {"1": 0.72, "5": 0.76, "10": 0.78, "15": 0.79, "30": 0.80, "60": 0.81, "EOD": 0.84},
    "GER40":  {"1": 0.71, "5": 0.75, "10": 0.77, "15": 0.78, "30": 0.79, "60": 0.80, "EOD": 0.83},
    "UK100":  {"1": 0.71, "5": 0.75, "10": 0.77, "15": 0.78, "30": 0.79, "60": 0.80, "EOD": 0.83},
}

PAYOUTS_IQOPTION = {
    "EURUSD": {"1": 0.82, "5": 0.87, "15": 0.90, "30": 0.91, "60": 0.92},
    "GBPUSD": {"1": 0.81, "5": 0.86, "15": 0.89, "30": 0.90, "60": 0.91},
    "USDJPY": {"1": 0.82, "5": 0.87, "15": 0.90, "30": 0.91, "60": 0.92},
    "EURGBP": {"1": 0.80, "5": 0.85, "15": 0.88, "30": 0.89, "60": 0.90},
    "XAUUSD": {"1": 0.78, "5": 0.83, "15": 0.86, "30": 0.87, "60": 0.88},
    "BTCUSD": {"1": 0.75, "5": 0.80, "15": 0.83, "30": 0.84, "60": 0.85},
}

PAYOUTS_POCKET = {
    "EURUSD": {"1": 0.80, "5": 0.85, "15": 0.88, "30": 0.89, "60": 0.90},
    "GBPUSD": {"1": 0.79, "5": 0.84, "15": 0.87, "30": 0.88, "60": 0.89},
    "USDJPY": {"1": 0.80, "5": 0.85, "15": 0.88, "30": 0.89, "60": 0.90},
    "EURGBP": {"1": 0.78, "5": 0.83, "15": 0.86, "30": 0.87, "60": 0.88},
    "XAUUSD": {"1": 0.77, "5": 0.82, "15": 0.85, "30": 0.86, "60": 0.87},
    "BTCUSD": {"1": 0.74, "5": 0.79, "15": 0.82, "30": 0.83, "60": 0.84},
}

PAYOUTS_QUOTEX = {
    "EURUSD": {"1": 0.81, "5": 0.86, "15": 0.89, "30": 0.90, "60": 0.91},
    "GBPUSD": {"1": 0.80, "5": 0.85, "15": 0.88, "30": 0.89, "60": 0.90},
    "USDJPY": {"1": 0.81, "5": 0.86, "15": 0.89, "30": 0.90, "60": 0.91},
    "EURGBP": {"1": 0.79, "5": 0.84, "15": 0.87, "30": 0.88, "60": 0.89},
    "XAUUSD": {"1": 0.78, "5": 0.83, "15": 0.86, "30": 0.87, "60": 0.88},
    "BTCUSD": {"1": 0.75, "5": 0.80, "15": 0.83, "30": 0.84, "60": 0.85},
}

# Genérico conservador (mínimo común)
PAYOUTS_GENERIC = {
    "EURUSD": {"1": 0.70, "5": 0.75, "10": 0.77, "15": 0.78, "30": 0.80, "60": 0.82, "EOD": 0.85},
    "GBPUSD": {"1": 0.69, "5": 0.74, "10": 0.76, "15": 0.77, "30": 0.79, "60": 0.81, "EOD": 0.84},
    "USDJPY": {"1": 0.70, "5": 0.75, "10": 0.77, "15": 0.78, "30": 0.80, "60": 0.82, "EOD": 0.85},
    "EURGBP": {"1": 0.68, "5": 0.73, "10": 0.75, "15": 0.76, "30": 0.78, "60": 0.80, "EOD": 0.83},
    "XAUUSD": {"1": 0.67, "5": 0.72, "10": 0.74, "15": 0.75, "30": 0.77, "60": 0.79, "EOD": 0.82},
    "BTCUSD": {"1": 0.65, "5": 0.70, "10": 0.72, "15": 0.73, "30": 0.75, "60": 0.77, "EOD": 0.80},
    "DEFAULT": {"1": 0.65, "5": 0.70, "10": 0.72, "15": 0.73, "30": 0.75, "60": 0.77, "EOD": 0.80},
}

ALL_BROKERS = {
    "deriv": PAYOUTS_DERIV,
    "iqoption": PAYOUTS_IQOPTION,
    "pocket": PAYOUTS_POCKET,
    "quotex": PAYOUTS_QUOTEX,
    "generic": PAYOUTS_GENERIC,
}


@dataclass
class PayoutTable:
    """Tabla de payouts para un activo específico."""
    broker: str
    simbolo: str
    payouts: Dict[str, float] = field(default_factory=dict)
    
    def get(self, expiry_minutes: int) -> float:
        """Obtiene payout para un horizonte en minutos."""
        key = str(expiry_minutes)
        if key in self.payouts:
            return self.payouts[key]
        if expiry_minutes >= 1440 and "EOD" in self.payouts:
            return self.payouts["EOD"]
        
        # Buscar el más cercano menor o igual
        for k, v in sorted(self.payouts.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 9999):
            if k.isdigit() and int(k) <= expiry_minutes:
                continue
            if k.isdigit() and int(k) > expiry_minutes:
                return v
        # Fallback al máximo disponible
        return max(self.payouts.values()) if self.payouts else 0.75
    
    def get_all(self) -> Dict[str, float]:
        return self.payouts.copy()


def get_payout_table(broker: str, simbolo: str) -> PayoutTable:
    """Obtiene tabla de payouts para broker y símbolo."""
    broker = broker.lower()
    simbolo = simbolo.upper()
    
    broker_data = ALL_BROKERS.get(broker, PAYOUTS_GENERIC)
    payouts = broker_data.get(simbolo, broker_data.get("DEFAULT", PAYOUTS_GENERIC["DEFAULT"]))
    
    return PayoutTable(broker=broker, simbolo=simbolo, payouts=payouts)


def get_available_symbols(broker: str) -> list:
    """Lista símbolos disponibles para un broker."""
    broker = broker.lower()
    return list(ALL_BROKERS.get(broker, PAYOUTS_GENERIC).keys())


def get_best_payout(simbolo: str, expiry_minutes: int) -> tuple:
    """Obtiene el mejor payout entre todos los brokers para un símbolo/horizonte."""
    best_payout = 0.0
    best_broker = "generic"
    
    for broker_name, broker_data in ALL_BROKERS.items():
        if broker_name == "generic":
            continue
        payouts = broker_data.get(simbolo.upper(), {})
        if str(expiry_minutes) in payouts:
            p = payouts[str(expiry_minutes)]
            if p > best_payout:
                best_payout = p
                best_broker = broker_name
    
    return best_broker, best_payout