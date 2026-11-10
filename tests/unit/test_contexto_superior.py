# -*- coding: utf-8 -*-
"""Regresión: el contexto superior no puede contener datos futuros.

El bug original incluía la vela H1/H4/D1 en formación con su OHLC completo,
calculado a partir de M15 posteriores al instante de decisión. Estos tests
construyen velas futuras con extremos imposibles: si el contexto las usa,
el high/low del frame se dispara y el test falla.
"""
import numpy as np
import pandas as pd
import pytest

from kernel.contexto_superior import (
    ContextoSuperiorCausal,
    TF_MINUTOS,
    _bucket_start,
)
from kernel.feeds.csv_resample import resamplear_ohlc


def _m15_sintetico(n=800):
    idx = pd.date_range("2026-01-05 00:00", periods=n, freq="15min", tz="UTC")
    base = 1.1000 + np.arange(n) * 0.00001
    df = pd.DataFrame(
        {
            "open": base,
            "high": base + 0.0002,
            "low": base - 0.0002,
            "close": base + 0.00005,
            "volume": np.arange(n, dtype=float) + 1.0,
        },
        index=idx,
    )
    return df


def _envenenar_futuro(df, corte):
    """Velas posteriores al corte con extremos y volumen imposibles."""
    df = df.copy()
    fut = df.index > corte
    df.loc[fut, "high"] = 9_999.0
    df.loc[fut, "low"] = -9_999.0
    df.loc[fut, "volume"] = 10**9
    return df


@pytest.mark.parametrize("tf", list(TF_MINUTOS))
def test_frame_no_usa_velas_posteriores(tf):
    df = _m15_sintetico()
    corte = df.index[603]  # dentro de un bucket, no en el borde
    envenenado = _envenenar_futuro(df, corte)
    ctx = ContextoSuperiorCausal(envenenado)
    frame = ctx.frame(tf, corte, tail=500)

    assert len(frame) > 0
    decision = corte + pd.Timedelta(minutes=15)

    # Todas las filas pertenecen a buckets que empezaron antes de la decisión.
    assert (frame.index < decision).all()
    # La última fila es el bucket en formación y cierra su OHLC en el corte.
    assert frame.index[-1] == _bucket_start(corte, tf)
    assert frame["close"].iloc[-1] == pytest.approx(float(df.loc[corte, "close"]))
    # Ningún extremo puede venir de una vela futura envenenada.
    assert frame["high"].max() < 9_000
    assert frame["low"].min() > -9_000
    # El volumen de la vela parcial no puede incluir el futuro.
    assert frame["volume"].iloc[-1] < 10**8


def test_frame_ultima_vela_es_agregado_manual():
    df = _m15_sintetico()
    corte = df.index[603]
    ctx = ContextoSuperiorCausal(df)
    frame = ctx.frame("H4", corte, tail=50)
    inicio = _bucket_start(corte, "H4")
    seg = df.loc[inicio:corte]
    ultima = frame.iloc[-1]
    assert frame.index[-1] == inicio
    assert ultima["open"] == pytest.approx(seg["open"].iloc[0])
    assert ultima["high"] == pytest.approx(seg["high"].max())
    assert ultima["low"] == pytest.approx(seg["low"].min())
    assert ultima["close"] == pytest.approx(seg["close"].iloc[-1])
    assert ultima["volume"] == pytest.approx(seg["volume"].sum())


def test_el_bug_original_habria_fallado():
    """La vela completa resampleada sí contiene el futuro; la causal no."""
    df = _m15_sintetico()
    corte = df.index[603]
    envenenado = _envenenar_futuro(df, corte)
    inicio = _bucket_start(corte, "H4")
    completa = resamplear_ohlc(envenenado, "H4").loc[inicio]
    causal = ContextoSuperiorCausal(envenenado).frame("H4", corte).iloc[-1]
    assert completa["high"] == 9_999.0
    assert causal["high"] < 9_000


def test_base_d1_solo_aporta_dias_cerrados():
    df = _m15_sintetico()
    corte = df.index[603]
    dia = _bucket_start(corte, "D1")
    base = pd.DataFrame(
        {
            "open": [1.0, 2.0, 3.0],
            "high": [1.1, 2.1, 3.1],
            "low": [0.9, 1.9, 2.9],
            "close": [1.05, 2.05, 3.05],
            "volume": [10.0, 20.0, 30.0],
        },
        index=pd.DatetimeIndex(
            [dia - pd.Timedelta(days=3), dia - pd.Timedelta(days=2), dia]
        ),
    )
    ctx = ContextoSuperiorCausal(df, bases={"D1": base})
    frame = ctx.frame("D1", corte)
    # El día actual de la base (futuro/parcial) se reemplaza por el agregado M15.
    assert frame.index[-1] == dia
    assert frame["close"].iloc[-1] == pytest.approx(float(df.loc[corte, "close"]))
    assert (frame.index < dia).sum() >= 2
