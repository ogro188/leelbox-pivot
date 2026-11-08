# -*- coding: utf-8 -*-
"""
Tests de regresión D0–D5 (directiva D08).

Cada test reproduce con datos armados a mano uno de los bugs corregidos
en D01–D06, sin depender de data/*.csv (que son sintéticos):

1) D0 con tendencia alcista armada a mano -> dir_estructura == "ALCISTA"
2) D1: vela mecha-rompe-cierra-adentro -> direction == 0 (y confirmada -> 1)
3) D2: el mismo barrido no genera 2 señales en barras consecutivas
4) D4: vela bajista + impulso alcista -> direction == 1 (impulso, no color OB)

Extras de contrato:
- D03: D1 (cierre confirmado) y D2_ANTICIPACION no coexisten para el mismo lado.
- D05: D3 no reporta fvg_mitigated como bool verificado en la vela de formación.
"""
import sys
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.d0_estructura import EstructuraProvider
from core.d1_ruptura import DetectorD1
from core.d2_sweep import DetectorD2
from core.d2_anticipacion import DetectorD2Anticipacion
from core.d3_fvg import DetectorD3
from core.d4_orderblock import DetectorD4
from core.base import Contexto as CoreContexto

ATR = 0.0005  # ATR14 artificial para todos los tests (en unidades de precio)
POINT = 0.00001


def build_df(rows):
    """rows: lista de (open, high, low, close) en orden cronológico.

    Devuelve un DataFrame indexado por tiempo con 15 min entre velas.
    """
    n = len(rows)
    fechas = [datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=15 * i) for i in range(n)]
    df = pd.DataFrame(
        {
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "volume": [100] * n,
        },
        index=pd.DatetimeIndex(fechas),
    )
    return df


def build_ctx(df_m15, df_h1=None, df_h4=None):
    ctx = CoreContexto(df_m15=df_m15, df_h1=df_h1, df_h4=df_h4, df_d1=None)
    ctx.g_atr14_buffer = [ATR] * 10
    ctx.g_atr8_buffer = [ATR] * 10
    ctx.g_atr30_buffer = [ATR] * 10
    ctx.g_ema21_buffer = [0.0] * 10
    ctx.g_ema50_buffer = [0.0] * 10
    ctx.g_rsi14_buffer = [50.0] * 10
    ctx.g_ema50_d1_buffer = []
    ctx.g_ema200_d1_buffer = []
    ctx.g_ema20_h4_buffer = []
    ctx.g_ema50_h4_buffer = []
    ctx.point = POINT
    ctx.session = "LONDON"
    ctx.kill_zone = "NONE"
    return ctx


# ---------------------------------------------------------------------------
# 1) D01 — D0 con tendencia alcista armada a mano -> "ALCISTA"
#
# D0 detecta los pivots sobre df_h1 (>=50 velas) escaneando shifts 3..21
# (depth=2, lookback=24). Se arman 60 velas: padding plano (sin pivots,
# vecinos iguales descalifican) + patrón colocado entre shifts 0..14:
#   ALCISTA:  swing high 1.0030 (shift 12) -> swing low 1.0015 (shift 9)
#             -> swing high 1.0045 (shift 6) -> swing low 1.0025 (shift 4)
#   highs cronologico = [1.0045, 1.0030] -> HH; lows = [1.0025, 1.0015] -> HL
# ---------------------------------------------------------------------------

_PAD = (1.0010, 1.0020, 1.0000, 1.0010)  # padding plano: sin pivots


def _d0_dir_for(rows):
    df = build_df(rows)
    ctx = build_ctx(df, df_h1=df)
    est = EstructuraProvider(ctx).actualizar()
    return est.dir_estructura


def test_d01_d0_tendencia_alcista_da_alcista():
    # rows en orden cronologico (indice 0 = mas antiguo = shift 59)
    rows = [_PAD] * 40                    # shifts 59..20
    rows += [_PAD] * 7                    # shifts 19..13
    rows += [(1.0022, 1.0030, 1.0012, 1.0028)]   # shift 12: swing high A
    rows += [(1.0020, 1.0025, 1.0018, 1.0022)] * 2   # shifts 11,10
    rows += [(1.0018, 1.0025, 1.0015, 1.0020)]   # shift 9: swing low A
    rows += [(1.0020, 1.0025, 1.0018, 1.0022)] * 2   # shifts 8,7
    rows += [(1.0038, 1.0045, 1.0030, 1.0040)]   # shift 6: swing high B (HH)
    rows += [(1.0030, 1.0038, 1.0028, 1.0035)]   # shift 5
    rows += [(1.0030, 1.0038, 1.0025, 1.0035)]   # shift 4: swing low B (HL)
    rows += [(1.0032, 1.0040, 1.0028, 1.0038)]   # shift 3
    rows += [(1.0035, 1.0042, 1.0030, 1.0040)]   # shift 2
    rows += [(1.0036, 1.0044, 1.0032, 1.0042)]   # shift 1
    rows += [(1.0038, 1.0046, 1.0034, 1.0044)]   # shift 0
    assert len(rows) == 60
    assert _d0_dir_for(rows) == "ALCISTA"


def test_d01_d0_tendencia_bajista_da_bajista():
    # Espejo exacto del alcista (high<->low reflejados): LH + LL.
    rows = [(1.0030, 1.0040, 1.0020, 1.0030)] * 47    # shifts 59..13
    rows += [(1.0012, 1.0028, 1.0010, 1.0018)]        # shift 12: swing low A
    rows += [(1.0018, 1.0022, 1.0015, 1.0020)] * 2    # shifts 11,10
    rows += [(1.0020, 1.0025, 1.0015, 1.0022)]        # shift 9: swing high A
    rows += [(1.0018, 1.0022, 1.0015, 1.0020)] * 2    # shifts 8,7
    rows += [(1.0000, 1.0010, 0.9995, 1.0002)]        # shift 6: swing low B (LL)
    rows += [(1.0005, 1.0012, 1.0002, 1.0010)]        # shift 5
    rows += [(1.0005, 1.0015, 1.0002, 1.0010)]        # shift 4: swing high B (LH)
    rows += [(1.0002, 1.0012, 1.0000, 1.0008)]        # shift 3
    rows += [(1.0000, 1.0010, 0.9998, 1.0005)]        # shift 2
    rows += [(0.9998, 1.0008, 0.9996, 1.0004)]        # shift 1
    rows += [(0.9996, 1.0006, 0.9994, 1.0002)]        # shift 0
    assert len(rows) == 60
    assert _d0_dir_for(rows) == "BAJISTA"


# ---------------------------------------------------------------------------
# 2) D02 — D1 exige cierre fuera del rango
# ---------------------------------------------------------------------------

RANGO = [(1.0000, 1.0010, 0.9990, 1.0000)] * 10  # rango plano de 10 velas


def test_d02_d1_mecha_rompe_cierra_adentro_da_direction_0():
    # La vela 0 rompe el techo del rango (1.0010) con la mecha (1.0030)
    # pero cierra ADENTRO del rango (1.0005).
    rows = RANGO + [(1.0008, 1.0030, 1.0002, 1.0005)]
    ctx = build_ctx(build_df(rows))
    sig = DetectorD1().detectar(ctx)
    assert sig is not None
    assert sig.direction == 0, "mecha que rompe sin cierre fuera del rango NO es ruptura"


def test_d02_d1_cierre_fuera_del_rango_da_direction_1():
    # Ahora la vela 0 cierra por encima del techo: ruptura confirmada.
    rows = RANGO + [(1.0008, 1.0030, 1.0002, 1.0025)]
    ctx = build_ctx(build_df(rows))
    sig = DetectorD1().detectar(ctx)
    assert sig is not None
    assert sig.direction == 1
    # La penetración se mide sobre el cierre confirmado.
    assert sig.filtro_penetracion_atr == (1.0025 - 1.0010) / ATR


def test_d02_d1_cierre_bajo_el_piso_da_direction_menos_1():
    rows = RANGO + [(0.9992, 0.9998, 0.9970, 0.9975)]
    ctx = build_ctx(build_df(rows))
    sig = DetectorD1().detectar(ctx)
    assert sig is not None
    assert sig.direction == -1


# ---------------------------------------------------------------------------
# 3) D03 — exclusión mutua D1 / D2_ANTICIPACION
# ---------------------------------------------------------------------------

def test_d03_d2_anticipacion_no_dispara_si_el_cierre_confirma_ruptura():
    # Misma vela que en test_d02_d1_cierre_fuera_del_rango: mecha Y cierre
    # fuera del rango -> D1 la toma; D2_ANTICIPACION no debe dar señal PUT.
    rows = RANGO + [(1.0008, 1.0030, 1.0002, 1.0025)]
    ctx = build_ctx(build_df(rows))
    sig = DetectorD2Anticipacion().detectar(ctx)
    assert sig is not None
    assert sig.direction != -1, (
        "D2_ANTICIPACION no puede anticipar rechazo de un nivel que la vela "
        "ya cerró por encima (eso es ruptura confirmada, dominio de D1)"
    )


def test_d03_d2_anticipacion_dispara_con_mecha_sin_confirmacion():
    # Mecha rompe pero cierre adentro: eso SÍ es anticipación.
    rows = RANGO + [(1.0008, 1.0030, 1.0002, 1.0005)]
    ctx = build_ctx(build_df(rows))
    sig = DetectorD2Anticipacion().detectar(ctx)
    assert sig is not None
    assert sig.direction == -1


# ---------------------------------------------------------------------------
# 4) D04 — el mismo barrido no se detecta dos veces en barras consecutivas
# ---------------------------------------------------------------------------

def test_d04_d2_mismo_barrido_no_genera_senal_dos_veces():
    # Barrido con mecha pronunciada en la vela -1 (shift 1). Si el detector
    # revisara también shift 2, al avanzar una vela re-detectaría el mismo
    # evento. Con la ventana fijada a shift 1, al avanzar la vela el barrido
    # queda en shift 2 y NO debe detectarse.
    sweep_bar = (1.0000, 1.0002, 0.9950, 1.0001)   # mecha abajo profunda, cierre sobre el piso
    rows = [
        (1.0000, 1.0010, 0.9990, 1.0000),   # -4
        (1.0000, 1.0010, 0.9990, 1.0000),   # -3 (piso del rango)
        (1.0000, 1.0010, 0.9990, 1.0000),   # -2
        sweep_bar,                            # -1: el barrido
        (1.0001, 1.0008, 0.9995, 1.0005),   #  0: vela actual
    ]
    df = build_df(rows)

    ctx0 = build_ctx(df)
    sig0 = DetectorD2().detectar(ctx0)
    assert sig0 is not None and sig0.direction == 1, "el barrido en shift 1 debe detectarse"

    # Avanzar una vela: el barrido queda ahora en shift 2.
    rows2 = rows + [(1.0005, 1.0012, 0.9998, 1.0010)]
    ctx1 = build_ctx(build_df(rows2))
    sig1 = DetectorD2().detectar(ctx1)
    assert sig1 is not None
    assert sig1.direction == 0, "el mismo barrido NO puede re-detectarse desde shift 2"


# ---------------------------------------------------------------------------
# 5) D05 — fvg_mitigated no es evaluable en la vela de formación
# ---------------------------------------------------------------------------

def test_d05_d3_fvg_mitigated_no_es_bool_verificado():
    # Vela 0 forma un FVG alcista con la vela -2 (gap entre high(-2) y low(0)).
    rows = [
        (1.0000, 1.0010, 0.9990, 1.0000),   # -4
        (1.0000, 1.0010, 0.9990, 1.0000),   # -3
        (1.0012, 1.0020, 1.0010, 1.0018),   # -2: vela A (alcista)
        (1.0018, 1.0030, 1.0015, 1.0028),   # -1: vela B (impulso)
        (1.0030, 1.0040, 1.0025, 1.0038),   #  0: vela C (forma el gap, lejos del nivel)
    ]
    ctx = build_ctx(build_df(rows))
    sig = DetectorD3().detectar(ctx)
    assert sig is not None
    assert sig.fvg_mitigated is None, (
        "fvg_mitigated no es evaluable en la vela de formación del gap "
        "(comparación tautológica): debe ser None, no un bool verificado"
    )


# ---------------------------------------------------------------------------
# 6) D06 — D4 señala en la dirección del impulso
# ---------------------------------------------------------------------------

def test_d06_d4_vela_bajista_con_impulso_alcista_da_call():
    # Vela -2: bajista con cuerpo grande (OB). Vela -1: impulso alcista fuerte
    # SIN solapar el rango del OB (si lo solapara, contaria como "tested" y el
    # OB se descarta). La senal debe ser CALL (direccion del impulso).
    rows = [
        (1.0000, 1.0010, 0.9990, 1.0000),   # -4
        (1.0000, 1.0010, 0.9990, 1.0000),   # -3
        (1.0020, 1.0022, 0.9980, 0.9985),   # -2: OB bajista (cuerpo 0.83)
        (1.0030, 1.0090, 1.0028, 1.0085),   # -1: impulso alcista, low > OB high
        (1.0020, 1.0030, 1.0005, 1.0010),   #  0: retroceso que entra al OB
    ]
    ctx = build_ctx(build_df(rows))
    sig = DetectorD4().detectar(ctx)
    assert sig is not None
    assert sig.ob_bars_ago == 2, "el OB es la vela bajista de shift 2"
    assert sig.direction == 1, (
        "la direccion de la senal es la del IMPULSO (alcista), no el color "
        "de la vela origen (bajista)"
    )


def test_d06_d4_vela_alcista_con_impulso_bajista_da_put():
    rows = [
        (1.0000, 1.0010, 0.9990, 1.0000),   # -4
        (1.0000, 1.0010, 0.9990, 1.0000),   # -3
        (0.9980, 1.0020, 0.9978, 1.0015),   # -2: OB alcista
        (0.9970, 0.9975, 0.9900, 0.9905),   # -1: impulso bajista, high < OB low
        (1.0010, 1.0018, 0.9985, 1.0000),   #  0: retroceso hacia arriba
    ]
    ctx = build_ctx(build_df(rows))
    sig = DetectorD4().detectar(ctx)
    assert sig is not None
    assert sig.ob_bars_ago == 2
    assert sig.direction == -1


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
