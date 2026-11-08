# -*- coding: utf-8 -*-
"""
PIVOT Binary - Estrategia PIVOT adaptada para opciones binarias.
Usa los mismos detectores D0-D5 del core, pero genera BinarySeñal con expiración temporal y payout.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from kernel.contrato import (
    Estrategia, Contexto, ActivoInfo, Señal,
    BinarySeñal, BinaryActivoInfo
)
from core.motor_v8 import PivotRadarEngine


class PivotBinary(Estrategia):
    """
    Estrategia PIVOT para opciones binarias.
    
    Reutiliza el motor PivotRadarEngine (detectores D0-D5) pero:
    - Convierte señales a BinarySeñal con expiración temporal
    - Añade payout del activo
    - Filtra por confianza mínima configurable
    - Filtra por kill zones y sesiones si se configura
    """
    
    nombre = "pivot_binary"
    version = "1.0"
    timeframes = ["M15", "H1", "H4", "D1"]
    eventos = ["candle_close"]
    
    # Parámetros configurables
    parametros = {
        "expiry_minutes": {"tipo": "int", "default": 15, "min": 1, "max": 1440, 
                          "descripcion": "Minutos hasta expiración (1, 5, 15, 30, 60, EOD=1440)"},
        "confianza_minima": {"tipo": "float", "default": 60.0, "min": 30.0, "max": 95.0,
                            "descripcion": "Confianza mínima (0-100) para tomar la señal"},
        "usar_kill_zones": {"tipo": "bool", "default": True,
                           "descripcion": "Solo operar en kill zones (London Open, NY Open)"},
        "usar_trend_d1": {"tipo": "bool", "default": True,
                         "descripcion": "Filtrar señales contra tendencia D1"},
        "usar_sesion": {"tipo": "bool", "default": True,
                       "descripcion": "Solo operar en sesiones London/NY (no Asia/Out)"},
        "min_calidad_sweep": {"tipo": "float", "default": 50.0, "min": 0.0, "max": 100.0,
                             "descripcion": "Calidad mínima sweep para D2/D5"},
        "min_calidad_fvg": {"tipo": "float", "default": 50.0, "min": 0.0, "max": 100.0,
                           "descripcion": "Calidad mínima FVG para D3"},
        "min_calidad_ob": {"tipo": "float", "default": 50.0, "min": 0.0, "max": 100.0,
                          "descripcion": "Calidad mínima OB para D4"},
        "min_calidad_mss": {"tipo": "float", "default": 50.0, "min": 0.0, "max": 100.0,
                           "descripcion": "Calidad mínima MSS para D5"},
        "pivot_depth": {"tipo": "int", "default": 2, "min": 1, "max": 5,
                       "descripcion": "Profundidad pivots para D0"},
        "pivot_lookback": {"tipo": "int", "default": 24, "min": 10, "max": 100,
                          "descripcion": "Lookback pivots para D0"},
        "n_ruptura": {"tipo": "int", "default": 4, "min": 2, "max": 20,
                     "descripcion": "Velas para ruptura D1"},
        "d1_atr_threshold": {"tipo": "float", "default": 0.50, "min": 0.1, "max": 2.0,
                            "descripcion": "Umbral ATR para ruptura D1"},
        "sweep_wick_min": {"tipo": "float", "default": 0.55, "min": 0.3, "max": 0.9,
                          "descripcion": "Wick mínimo para sweep D2/D5"},
        "reclaim_body_min": {"tipo": "float", "default": 0.55, "min": 0.3, "max": 0.9,
                            "descripcion": "Body mínimo reclaim D2/D5"},
        "fvg_min_size_atr": {"tipo": "float", "default": 0.20, "min": 0.1, "max": 1.0,
                            "descripcion": "Tamaño mínimo FVG en ATR"},
        "fvg_body_ratio": {"tipo": "float", "default": 0.55, "min": 0.3, "max": 0.9,
                          "descripcion": "Body ratio mínimo FVG"},
        "ob_impulse_min": {"tipo": "float", "default": 0.70, "min": 0.3, "max": 2.0,
                          "descripcion": "Impulso mínimo OB en ATR"},
        "mss_max_age_h4": {"tipo": "int", "default": 12, "min": 1, "max": 50,
                          "descripcion": "Máximo velas H4 para MSS válido"},
    }
    
    def __init__(self):
        self.engine: Optional[PivotRadarEngine] = None
        self._params: Dict[str, Any] = {}
    
    def setup(self, params: Dict[str, Any], activo: ActivoInfo) -> None:
        """Inicializa la estrategia con parámetros y activo."""
        self._params = {**self.get_default_params(), **params}
        
        # Crear motor PivotRadarEngine interno
        self.engine = PivotRadarEngine(
            symbol=activo.simbolo,
            ntfy_topic="",  # Sin alertas en backtest
            modo_test=True,
            n_ruptura=self._params.get("n_ruptura", 4),
            d1_atr_threshold=self._params.get("d1_atr_threshold", 0.50),
            sweep_wick_min=self._params.get("sweep_wick_min", 0.55),
            reclaim_body_min=self._params.get("reclaim_body_min", 0.55),
            pivot_depth=self._params.get("pivot_depth", 2),
            pivot_lookback=self._params.get("pivot_lookback", 24),
            sweep_n=self._params.get("sweep_n", 6),
            fvg_min_size_atr=self._params.get("fvg_min_size_atr", 0.20),
            fvg_body_ratio=self._params.get("fvg_body_ratio", 0.55),
            ob_impulse_min=self._params.get("ob_impulse_min", 0.70),
            mss_max_age_h4_bars=self._params.get("mss_max_age_h4", 12),
        )
    
    def detectar(self, ctx: Contexto) -> List[BinarySeñal]:
        """
        Detecta señales usando el motor PIVOT y convierte a BinarySeñal.
        """
        if self.engine is None:
            return []
        
        # Pasar datos al motor
        self.engine.on_data(ctx.df_m15, ctx.df_h1, ctx.df_h4, ctx.df_d1)
        
        binary_señales = []
        confianza_min = self._params.get("confianza_minima", 60.0)
        expiry_minutes = self._params.get("expiry_minutes", 15)
        
        for sig in self.engine.g_pending_signals:
            # Solo señales de la barra actual con dirección válida
            if sig.entry_time != ctx.tiempo or sig.direction == 0:
                continue
            
            # Filtrar por confianza
            conf_min = getattr(sig, 'hipotesis_prob_min', 0)
            if conf_min < confianza_min:
                continue
            
            # Filtro kill zones
            if self._params.get("usar_kill_zones", True):
                if sig.kill_zone == "NONE":
                    continue
            
            # Filtro tendencia D1
            if self._params.get("usar_trend_d1", True):
                if sig.direction == 1 and sig.trend_d1 == "BAJISTA":
                    continue
                if sig.direction == -1 and sig.trend_d1 == "ALCISTA":
                    continue
            
            # Filtro sesión
            if self._params.get("usar_sesion", True):
                if sig.session in ("ASIA", "OUT"):
                    continue
            
            # Filtros de calidad por detector
            if not self._passes_quality_filters(sig):
                continue
            
            # Convertir a BinarySeñal
            binary_sig = self._to_binary(sig, ctx, expiry_minutes)
            binary_señales.append(binary_sig)
        
        return binary_señales
    
    def _passes_quality_filters(self, sig: Señal) -> bool:
        """Verifica filtros de calidad según detector."""
        detector = sig.detector
        
        if detector in ("D2", "D2_ANTICIPACION", "D5"):
            calidad = getattr(sig, 'calidad_sweep', 0)
            if calidad < self._params.get("min_calidad_sweep", 50.0):
                return False
        
        if detector in ("D3", "D3_DEF"):
            calidad = getattr(sig, 'calidad_fvg', 0)
            if calidad < self._params.get("min_calidad_fvg", 50.0):
                return False
        
        if detector == "D4":
            calidad = getattr(sig, 'calidad_ob', 0)
            if calidad < self._params.get("min_calidad_ob", 50.0):
                return False
        
        if detector == "D5":
            calidad = getattr(sig, 'calidad_mss', 0)
            if calidad < self._params.get("min_calidad_mss", 50.0):
                return False
        
        return True
    
    def _to_binary(self, sig: Señal, ctx: Contexto, expiry_minutes: int) -> BinarySeñal:
        """Convierte Señal del motor a BinarySeñal."""
        # Obtener payout del activo binario
        activo_bin = ctx.activo
        payout_pct = 0.80
        if isinstance(activo_bin, BinaryActivoInfo):
            payout_pct = activo_bin.get_payout(expiry_minutes)
        
        # Mapear dirección
        option_type = "CALL" if sig.direction == 1 else "PUT"
        
        # Calcular expiry_timestamp
        entry_time = sig.entry_time
        if entry_time and entry_time.year > 2000:
            expiry_ts = entry_time + timedelta(minutes=expiry_minutes)
        else:
            expiry_ts = None
        
        # Confianza
        conf_min = getattr(sig, 'hipotesis_prob_min', 50)
        conf_max = getattr(sig, 'hipotesis_prob_max', 70)
        
        binary_sig = BinarySeñal(
            estrategia=self.nombre,
            simbolo=sig.symbol,
            direccion=sig.direction,
            precio=sig.entry_price,
            tiempo=entry_time,
            etiqueta=sig.tipo or detector,
            confianza=(conf_min, conf_max),
            narrativa=sig.hipotesis_texto,
            contexto={
                "detector": sig.detector,
                "tipo": sig.tipo,
                "filtros_pasados": getattr(sig, 'filtros_pasados', []),
                "filtros_fallados": getattr(sig, 'filtros_fallados', []),
                "calidad_sweep": getattr(sig, 'calidad_sweep', 0),
                "calidad_fvg": getattr(sig, 'calidad_fvg', 0),
                "calidad_ob": getattr(sig, 'calidad_ob', 0),
                "calidad_mss": getattr(sig, 'calidad_mss', 0),
                "conviccion": getattr(sig, 'conviccion', 'BAJA'),
            },
            expiry_minutes=expiry_minutes,
            expiry_timestamp=expiry_ts,
            payout_pct=payout_pct,
            contract_amount=10.0,  # Se sobrescribe en engine
        )
        
        return binary_sig


# Alias para compatibilidad
EstrategiaPivotBinary = PivotBinary


# Factory para registro
def create_pivot_binary() -> PivotBinary:
    return PivotBinary()