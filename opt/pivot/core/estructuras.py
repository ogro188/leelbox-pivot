#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Estructuras de datos compartidas (antes estaban en motor.py)."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Dict, Tuple, Optional, Set


def _utc_epoch() -> datetime:
    """Epoch timezone-aware: coherente con índices datetime64[UTC]."""
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass
class EstructuraRef:
    timestamp: datetime = field(default_factory=_utc_epoch)
    swing_high: float = 0.0
    swing_low: float = 0.0
    swing_high_ant: float = 0.0
    swing_low_ant: float = 0.0
    sweep_nivel: float = 0.0
    sweep_dir: int = 0
    zona_alta: float = 0.0
    zona_baja: float = 0.0
    en_zona: bool = False
    dir_estructura: str = "NEUTRO"
    valida: bool = False


@dataclass
class Signal:
    id: int = 0
    entry_time: datetime = field(default_factory=_utc_epoch)
    entry_bar_shift: int = -1
    symbol: str = ""
    direction: int = 0
    entry_price: float = 0.0
    detector: str = ""
    tipo: str = ""
    cr: float = 0.0
    bs: float = 0.0
    bs_pips: float = 0.0
    br: float = 0.0
    range_break_pips: float = 0.0
    nivel_estructural: float = 0.0
    sweep_wick_ratio: float = 0.0
    sweep_volume_ratio: float = 0.0
    reclaim_body_ratio: float = 0.0
    sweep_bars_ago: int = 0
    equal_hl_detected: bool = False
    level_swept: float = 0.0
    fvg_size_pips: float = 0.0
    fvg_size_atr: float = 0.0
    fvg_mitigated: bool = False
    fvg_top: float = 0.0
    fvg_bottom: float = 0.0
    ob_high: float = 0.0
    ob_low: float = 0.0
    ob_bars_ago: int = 0
    ob_impulse_atr: float = 0.0
    ob_confluence: bool = False
    mss_aligned: bool = False
    mss_bars_ago_h4: int = 0
    mss_direction: str = ""
    mss_level: float = 0.0
    atr14: float = 0.0
    spread_pips: float = 0.0
    volume_ratio: float = 0.0
    session: str = ""
    kill_zone: str = ""
    trend_d1: str = ""
    vol_expanding: bool = False
    vol_compressing: bool = False
    calidad_sweep: float = 0.0
    calidad_mss: float = 0.0
    calidad_fvg: float = 0.0
    calidad_ob: float = 0.0
    salud_tendencial: float = 0.0
    g1_compresion: float = 0.0
    g2_persistencia: float = 0.0
    g3_eficiencia: float = 0.0
    g4_agotamiento: float = 0.0
    conf_sweep_fvg: float = 0.0
    conf_completa: float = 0.0
    es_intravela: bool = True
    contexto_estructural: float = 0.0
    estructura_direccion: str = "NEUTRO"
    distancia_al_sweep: float = 0.0
    en_zona_estructural: bool = False
    hipotesis_causa: str = ""
    hipotesis_efecto: str = ""
    hipotesis_razon: str = ""
    hipotesis_invalidez: str = ""
    hipotesis_expiry_velas: int = 0
    hipotesis_expiry_minutos: int = 0
    hipotesis_prob_min: int = 0
    hipotesis_prob_max: int = 0
    hipotesis_zona: str = "NEUTRO"
    hipotesis_objetivo: float = 0.0
    hipotesis_texto: str = ""
    signal_age_bars: int = 0
    measured: List[bool] = field(default_factory=lambda: [False, False, False, False])
    retorno: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    mfe: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    mae: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    # Medicion con velas CERRADAS (contrato binario): el cierre de la vela h
    # posterior a la entrada solo existe cuando shift >= h + 1.
    medido_cerrado: List[bool] = field(default_factory=lambda: [False, False, False, False])
    retorno_cerrado: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    mfe_cerrado: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    mae_cerrado: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    gap_detected: bool = False
    completada: bool = False
    conviccion: str = ""
    velocidad_aproximacion: float = 50.0
    toques_nivel: int = 0
    displacement_post_sweep: bool = False
    regimen_volatilidad: str = "NORMAL"
    invalidez_estructural: float = 0.0
    objetivo_estructural: float = 0.0
    # Anclaje al horizonte del contrato (15 min): niveles alcanzables
    objetivo_operativo: float = 0.0
    invalidez_operativa: float = 0.0
    csv_written: bool = False

    # Filtros informacionales (no bloqueantes)
    filtros_pasados: List[str] = field(default_factory=list)
    filtros_fallados: List[str] = field(default_factory=list)
    filtro_penetracion_atr: float = 0.0
    filtro_body_ratio: float = 0.0
    filtro_volumen_ratio: float = 0.0
    filtro_retest: bool = False
    filtro_wick_ratio: float = 0.0
    filtro_reclaim_ratio: float = 0.0
    filtro_sweep_reciente: bool = False
    filtro_distancia_nivel: float = 0.0
    filtro_fvg_size_atr: float = 0.0
    filtro_fvg_body_ratio: float = 0.0
    filtro_fvg_dir_ok: bool = False
    filtro_ob_impulse: float = 0.0
    filtro_ob_body_ratio: float = 0.0
    filtro_ob_tested: bool = False
    filtro_ob_entering: bool = False
    filtro_ob_distancia: float = 0.0
    filtro_mss_aligned: bool = False
    filtro_mss_reciente: bool = False
    filtro_confluencias: int = 0


@dataclass
class AlertEntry:
    text: str = ""
    retry_count: int = 0
    last_retry: datetime = field(default_factory=_utc_epoch)
    created_at: datetime = field(default_factory=_utc_epoch)
    content_hash: str = ""


@dataclass
class MSSCache:
    valid: bool = False
    calc_time: datetime = field(default_factory=_utc_epoch)
    bars_ago: int = 0
    dir: str = ""
    level: float = 0.0


@dataclass
class ZonaCache:
    valid: bool = False
    calc_time: datetime = field(default_factory=_utc_epoch)
    mid: float = 0.0


@dataclass
class DetectorLatch:
    last_signal_bar: datetime = field(default_factory=_utc_epoch)
    last_pattern_key: str = ""
    has_fired_this_bar: bool = False
