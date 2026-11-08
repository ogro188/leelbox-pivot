#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D3 — Fair Value Gap (intravela). Filtros informacionales."""
from core.estructuras import Signal
from core.base import Contexto, Detector


class DetectorD3(Detector):
    nombre = "D3"

    def detectar(self, ctx: Contexto) -> Signal:
        ha = ctx._i_high(ctx.df_m15, 2)
        la = ctx._i_low(ctx.df_m15, 2)
        hb = ctx._i_high(ctx.df_m15, 1)
        lb = ctx._i_low(ctx.df_m15, 1)
        cb = ctx._i_close(ctx.df_m15, 1)
        ob = ctx._i_open(ctx.df_m15, 1)
        hc = ctx._i_high(ctx.df_m15, 0)
        lc2 = ctx._i_low(ctx.df_m15, 0)
        if ha == 0 or la == 0 or hb == 0 or lb == 0 or hc == 0 or lc2 == 0:
            return None
        atr14 = ctx.g_atr14_buffer[0] if ctx.g_atr14_buffer else 0.0
        if atr14 <= 0:
            return None

        fvg_alcista = ha < lc2
        fvg_bajista = la > hc

        sig = Signal()
        sig.entry_time = ctx._i_time(ctx.df_m15, 0)
        sig.entry_bar_shift = 0
        sig.entry_price = ctx._i_close(ctx.df_m15, 0)
        sig.detector = "D3"
        sig.es_intravela = True
        sig.atr14 = atr14 / ctx.point
        sig.session = ctx.session
        sig.kill_zone = ctx.kill_zone
        sig.estructura_direccion = ctx.estructura.dir_estructura if ctx.estructura else "NEUTRO"
        sig.regimen_volatilidad = ctx.regimen_vol
        sig.g1_compresion = ctx.g1
        sig.g2_persistencia = ctx.g2
        sig.g4_agotamiento = ctx.g4

        if not fvg_alcista and not fvg_bajista:
            sig.direction = 0
            sig.filtros_fallados.append("sin_fvg")
            sig.tipo = "D"
            return sig

        fvg_size = 0.0
        fvg_top = 0.0
        fvg_bottom = 0.0
        direction = 0
        if fvg_alcista:
            fvg_size = lc2 - ha
            fvg_top = lc2
            fvg_bottom = ha
            direction = 1
        else:
            fvg_size = la - hc
            fvg_top = la
            fvg_bottom = hc
            direction = -1

        sig.direction = direction
        sig.fvg_top = fvg_top
        sig.fvg_bottom = fvg_bottom

        if fvg_size <= 0:
            sig.filtros_fallados.append("fvg_size_invalido")
            sig.tipo = "D"
            return sig

        fvg_size_atr = fvg_size / atr14
        sig.fvg_size_atr = fvg_size_atr
        sig.filtro_fvg_size_atr = fvg_size_atr
        if fvg_size_atr >= ctx.inp_fvg_min_size_atr:
            sig.filtros_pasados.append("fvg_size_atr")
        else:
            sig.filtros_fallados.append("fvg_size_atr")

        br_b = abs(cb - ob) / (hb - lb) if (hb - lb) > 0 else 0
        sig._fvg_br = br_b
        sig.filtro_fvg_body_ratio = br_b
        if br_b >= ctx.inp_fvg_body_ratio:
            sig.filtros_pasados.append("fvg_body_ratio")
        else:
            sig.filtros_fallados.append("fvg_body_ratio")

        dir_ok = (fvg_alcista and cb > ob) or (fvg_bajista and cb < ob)
        sig.filtro_fvg_dir_ok = dir_ok
        if dir_ok:
            sig.filtros_pasados.append("fvg_dir_ok")
        else:
            sig.filtros_fallados.append("fvg_dir_ok")

        mit_level = fvg_bottom + (fvg_top - fvg_bottom) * ctx.inp_fvg_mitig_umbral
        price0 = ctx._i_close(ctx.df_m15, 0)
        # Mitigacion NO evaluable en la vela de formacion del gap: fvg_top/bottom
        # se calculan con la misma vela 0 (lc2 = low de la vela 0), por lo que
        # price0 <= mit_level era matematicamente imposible (close(0) >= low(0)
        # = fvg_top > mit_level siempre). Evaluarla requiere seguimiento
        # multi-vela con estado de gaps abiertos (ver directiva D05, fix completo).
        # price0 se conserva: el bloque "defendido" si lo usa.
        sig.fvg_mitigated = None

        defendido = False
        if direction == 1 and price0 > fvg_top:
            defendido = True
        if direction == -1 and price0 < fvg_bottom:
            defendido = True

        det = "D3_DEF" if defendido else "D3"
        sig.detector = det

        ok_mss, mss_bars, mss_dir, mss_level = ctx.detect_mss_h4()
        sig.mss_aligned = ok_mss
        sig.mss_bars_ago_h4 = mss_bars
        sig.mss_direction = mss_dir
        sig.mss_level = mss_level
        sig.filtro_mss_aligned = ok_mss

        slope = (ctx.g_ema21_buffer[0] - ctx.g_ema21_buffer[3]) / atr14 if len(ctx.g_ema21_buffer) > 3 else 0.0
        sig.tipo = self.clasificar(sig, ctx, fvg_size_atr, br_b, slope)
        return sig

    def _get_trend_velas(self, ctx: Contexto) -> int:
        if len(ctx.g_ema21_buffer) < 2 or len(ctx.g_ema50_buffer) < 2:
            return 0
        up = ctx.g_ema21_buffer[1] > ctx.g_ema50_buffer[1]
        down = ctx.g_ema21_buffer[1] < ctx.g_ema50_buffer[1]
        if not up and not down:
            return 0
        count = 0
        max_i = min(55, len(ctx.g_ema21_buffer), len(ctx.g_ema50_buffer))
        for i in range(1, max_i):
            u = ctx.g_ema21_buffer[i] > ctx.g_ema50_buffer[i]
            d = ctx.g_ema21_buffer[i] < ctx.g_ema50_buffer[i]
            if not u and not d:
                continue
            if up and not u:
                break
            if down and not d:
                break
            count += 1
        return count

    def clasificar(self, sig: Signal, ctx: Contexto, fvg_size: float = None, br: float = None, slope: float = None) -> str:
        if fvg_size is None:
            fvg_size = sig.fvg_size_atr
        if br is None:
            br = getattr(sig, '_fvg_br', 0.0)
        if len(ctx.g_ema21_buffer) >= 2 and len(ctx.g_ema50_buffer) >= 2:
            up = ctx.g_ema21_buffer[1] > ctx.g_ema50_buffer[1]
            down = ctx.g_ema21_buffer[1] < ctx.g_ema50_buffer[1]
            if up and not down:
                trend = 1
            elif down and not up:
                trend = -1
            else:
                trend = 0
        else:
            trend = 0
        if fvg_size > 0.50 and br > 0.70 and trend >= 1:
            return "A"
        if fvg_size > 0.35 and br > 0.60:
            return "B"
        if fvg_size > ctx.inp_fvg_min_size_atr and br > ctx.inp_fvg_body_ratio:
            return "C"
        return "D"
