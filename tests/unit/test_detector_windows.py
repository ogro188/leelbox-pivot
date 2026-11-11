# -*- coding: utf-8 -*-
"""Ventanas y deduplicación de D1/D2/D4/D5.

Estos tests fijan las reglas que la auditoría encontró desalineadas:

- D1: la ruptura usa 4 velas (shifts 1..4), no 5.
- D2: el extremo previo incluye el shift 2 (ventana 2..7), no 3..7.
- D5: mismo extremo previo que D2 y metadata `sweep_bars_ago` /
  `sweep_volume_ratio`; el mismo barrido no se re-emite al pasar de
  shift 1 a shift 2.
- D4: el mismo OB no se re-emite mientras envejece de shift 2 a 4.

Los datos son armados a mano; no dependen de data/*.csv.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.base import Contexto as CoreContexto
from core.d1_ruptura import DetectorD1
from core.d2_sweep import DetectorD2
from core.d4_orderblock import DetectorD4
from core.d5_mss_sweep import DetectorD5

ATR = 0.0005
POINT = 0.00001


def build_df(rows):
    """rows: (open, high, low, close) en orden cronológico."""
    n = len(rows)
    fechas = [
        datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=15 * i)
        for i in range(n)
    ]
    return pd.DataFrame(
        {
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "volume": [100] * n,
        },
        index=pd.DatetimeIndex(fechas),
    )


def build_ctx(df_m15):
    ctx = CoreContexto(df_m15=df_m15, df_h1=None, df_h4=None, df_d1=None)
    ctx.g_atr14_buffer = [ATR] * 10
    ctx.g_atr8_buffer = [ATR] * 10
    ctx.g_atr30_buffer = [ATR] * 10
    ctx.g_ema21_buffer = [0.0] * 10
    ctx.g_ema50_buffer = [0.0] * 10
    ctx.g_rsi14_buffer = [50.0] * 10
    ctx.point = POINT
    ctx.session = "LONDON"
    ctx.kill_zone = "NONE"
    return ctx


def test_d1_ventana_excluye_la_quinta_vela():
    # La vela -5 tiene el high más alto (1.0100), pero está fuera de la
    # ventana de 4. La vela -4 (1.0050) es el extremo que debe usarse.
    rows = [
        (1.0000, 1.0100, 0.9990, 1.0050),   # -5: fuera de la ventana
        (1.0000, 1.0050, 0.9990, 1.0040),   # -4: extremo válido
        (1.0000, 1.0010, 0.9990, 1.0000),   # -3
        (1.0000, 1.0010, 0.9990, 1.0000),   # -2
        (1.0000, 1.0010, 0.9990, 1.0000),   # -1
        (1.0000, 1.0060, 0.9995, 1.0055),   #  0: rompe 1.0050
    ]
    sig = DetectorD1().detectar(build_ctx(build_df(rows)))
    assert sig is not None
    assert sig.direction == 1, "la ruptura de 4 velas debe detectarse"
    assert abs(sig.nivel_estructural - 1.0050) <= 1e-12, (
        "el nivel debe ser el máximo de shifts 1..4; la vela -5 no cuenta"
    )


def test_d2_ventana_incluye_el_shift_2():
    # El high de shift 2 (1.0050) es más alto que el de shifts 3..7 (1.0010).
    # La ventana correcta (2..7) fija el nivel en 1.0050.
    rows = [
        (1.0000, 1.0010, 0.9990, 1.0000),   # -7
        (1.0000, 1.0010, 0.9990, 1.0000),   # -6
        (1.0000, 1.0010, 0.9990, 1.0000),   # -5
        (1.0000, 1.0010, 0.9990, 1.0000),   # -4
        (1.0000, 1.0010, 0.9990, 1.0000),   # -3
        (1.0000, 1.0050, 0.9990, 1.0040),   # -2: extremo de la ventana
        (1.0000, 1.0060, 0.9990, 1.0005),   # -1: barrido
        (1.0005, 1.0010, 0.9995, 1.0000),   #  0
    ]
    sig = DetectorD2().detectar(build_ctx(build_df(rows)))
    assert sig is not None
    assert sig.direction == -1
    assert abs(sig.level_swept - 1.0050) <= 1e-12, (
        "el extremo previo debe incluir el shift 2, no solo 3..7"
    )
    assert sig.sweep_bars_ago == 1


def test_d5_ventana_y_metadata():
    rows = [
        (1.0000, 1.0010, 0.9995, 1.0000),   # -7
        (1.0000, 1.0010, 0.9995, 1.0000),   # -6
        (1.0000, 1.0010, 0.9995, 1.0000),   # -5
        (1.0000, 1.0010, 0.9995, 1.0000),   # -4
        (1.0000, 1.0010, 0.9995, 1.0000),   # -3
        (1.0000, 1.0010, 0.9991, 1.0000),   # -2: mínimo de la ventana
        (1.0000, 1.0005, 0.9986, 0.9998),   # -1: barrido con mecha
        (0.9998, 1.0005, 0.9995, 1.0000),   #  0
    ]
    ctx = build_ctx(build_df(rows))
    ctx.detect_mss_h4 = lambda: (True, 1, "ALCISTA", 1.0)
    sig = DetectorD5().detectar(ctx)
    assert sig is not None
    assert sig.direction == 1
    assert abs(sig.level_swept - 0.9991) <= 1e-12, (
        "el mínimo previo debe incluir el shift 2"
    )
    assert sig.sweep_bars_ago == 1, "la metadata debe apuntar al barrido real"
    assert sig.sweep_volume_ratio == 1.0, "el volumen del barrido no puede quedar en 0"


def test_d5_mismo_barrido_no_se_reemite():
    rows = [
        (1.0000, 1.0010, 0.9995, 1.0000),   # -7
        (1.0000, 1.0010, 0.9995, 1.0000),   # -6
        (1.0000, 1.0010, 0.9995, 1.0000),   # -5
        (1.0000, 1.0010, 0.9995, 1.0000),   # -4
        (1.0000, 1.0010, 0.9995, 1.0000),   # -3
        (1.0000, 1.0010, 0.9991, 1.0000),   # -2
        (1.0000, 1.0005, 0.9986, 0.9998),   # -1: barrido
        (0.9998, 1.0005, 0.9995, 1.0000),   #  0
    ]
    det = DetectorD5()

    ctx0 = build_ctx(build_df(rows))
    ctx0.detect_mss_h4 = lambda: (True, 1, "ALCISTA", 1.0)
    sig0 = det.detectar(ctx0)
    assert sig0 is not None and sig0.direction == 1

    # Al avanzar una vela, el mismo barrido pasa de shift 1 a shift 2.
    rows1 = rows + [(1.0000, 1.0004, 0.9995, 1.0000)]
    ctx1 = build_ctx(build_df(rows1))
    ctx1.detect_mss_h4 = lambda: (True, 1, "ALCISTA", 1.0)
    sig1 = det.detectar(ctx1)
    assert sig1 is not None
    assert sig1.direction == 0, "el mismo barrido no puede re-emitirse"
    assert sig1.sweep_bars_ago == 2, "la metadata debe reflejar el shift real"
    assert "barrido_duplicado" in sig1.filtros_fallados


def test_d4_mismo_ob_no_se_reemite():
    rows = [
        (1.0000, 1.0010, 0.9990, 1.0000),   # -3
        (1.0020, 1.0022, 0.9980, 0.9985),   # -2: OB bajista
        (1.0030, 1.0090, 1.0028, 1.0085),   # -1: impulso alcista
        (1.0085, 1.0095, 1.0030, 1.0090),   #  0: no toca el OB
    ]
    det = DetectorD4()

    sig0 = det.detectar(build_ctx(build_df(rows)))
    assert sig0 is not None and sig0.direction == 1
    assert sig0.ob_bars_ago == 2

    # El OB envejece a shift 3; la vela intermedia tampoco lo toca, así que
    # sin deduplicación se re-emitiría.
    rows1 = rows + [(1.0090, 1.0100, 1.0040, 1.0095)]
    sig1 = det.detectar(build_ctx(build_df(rows1)))
    assert sig1 is not None
    assert sig1.direction == 0, "el mismo OB no puede re-emitirse en shift 3"
    assert sig1.ob_bars_ago == 3
    assert "ob_duplicado" in sig1.filtros_fallados

    # Y tampoco en shift 4.
    rows2 = rows1 + [(1.0095, 1.0105, 1.0045, 1.0100)]
    sig2 = det.detectar(build_ctx(build_df(rows2)))
    assert sig2 is not None
    assert sig2.direction == 0, "el mismo OB no puede re-emitirse en shift 4"
    assert sig2.ob_bars_ago == 4
    assert "ob_duplicado" in sig2.filtros_fallados


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
