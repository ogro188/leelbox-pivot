#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D2_ANTICIPACION — Alerta temprana de sweep con confluencias. Filtros informacionales."""
from core.estructuras import Signal
from core.base import Contexto, Detector
from core.utils import clamp_0_100


class DetectorD2Anticipacion(Detector):
    nombre = "D2_ANTICIPACION"

    def detectar(self, ctx: Contexto) -> Signal:
        high0 = ctx._i_high(ctx.df_m15, 0)
        low0 = ctx._i_low(ctx.df_m15, 0)
        close0 = ctx._i_close(ctx.df_m15, 0)
        open0 = ctx._i_open(ctx.df_m15, 0)
        if high0 == 0 or low0 == 0 or close0 == 0 or open0 == 0:
            return None
        atr14 = ctx.g_atr14_buffer[0] if ctx.g_atr14_buffer else 0.0
        if atr14 <= 0:
            return None

        prior_high = ctx._i_high(ctx.df_m15, 1)
        prior_low = ctx._i_low(ctx.df_m15, 1)
        for k in range(2, ctx.inp_sweep_n + 1):
            h = ctx._i_high(ctx.df_m15, k)
            l = ctx._i_low(ctx.df_m15, k)
            if h == 0 or l == 0:
                break
            if h > prior_high:
                prior_high = h
            if l < prior_low:
                prior_low = l

        sweep_high = high0 > prior_high
        sweep_low = low0 < prior_low

        # Exclusion mutua con D1 (ruptura confirmada): si la vela YA cerro
        # fuera del rango, es dominio de D1 (con el fix D02 exige cierre), no
        # una anticipacion de rechazo. La anticipacion es justamente "la mecha
        # rompe pero el cierre todavia esta dentro".
        if sweep_high and close0 > prior_high:
            sweep_high = False
        if sweep_low and close0 < prior_low:
            sweep_low = False

        sig = Signal()
        sig.entry_time = ctx._i_time(ctx.df_m15, 0)
        sig.entry_bar_shift = 0
        sig.entry_price = close0
        sig.detector = self.nombre
        sig.es_intravela = True
        sig.atr14 = atr14 / ctx.point
        sig.session = ctx.session
        sig.kill_zone = ctx.kill_zone
        sig.estructura_direccion = ctx.estructura.dir_estructura if ctx.estructura else "NEUTRO"
        sig.g1_compresion = ctx.g1
        sig.g2_persistencia = ctx.g2
        sig.g4_agotamiento = ctx.g4
        sig.regimen_volatilidad = ctx.regimen_vol

        if not sweep_high and not sweep_low:
            sig.direction = 0
            sig.filtros_fallados.append("sin_sweep")
            sig.tipo = "D"
            return sig

        sweep_dir = -1 if sweep_high else 1
        nivel_barrido = prior_high if sweep_high else prior_low
        sig.direction = sweep_dir
        sig.level_swept = nivel_barrido

        rango = high0 - low0
        wick_ratio = (high0 - max(open0, close0)) / rango if sweep_high else (min(open0, close0) - low0) / rango
        sig.sweep_wick_ratio = wick_ratio
        sig.filtro_wick_ratio = wick_ratio
        if wick_ratio >= ctx.inp_sweep_wick_min * 0.6:
            sig.filtros_pasados.append("wick_ratio")
        else:
            sig.filtros_fallados.append("wick_ratio")

        confluencias = 0
        hay_fvg = False

        # Detección FVG
        for i in range(2, 6):
            ha = ctx._i_high(ctx.df_m15, i)
            la = ctx._i_low(ctx.df_m15, i)
            hb = ctx._i_high(ctx.df_m15, i - 1)
            lb = ctx._i_low(ctx.df_m15, i - 1)
            hc = ctx._i_high(ctx.df_m15, i - 2)
            lc2 = ctx._i_low(ctx.df_m15, i - 2)
            if ha == 0 or la == 0 or hb == 0 or lb == 0 or hc == 0 or lc2 == 0:
                continue

            if hc < la:
                ce = hc + (la - hc) * 0.5
                if abs(nivel_barrido - ce) < atr14 * 0.5:
                    hay_fvg = True
                    break
            elif lc2 > ha:
                ce = ha + (lc2 - ha) * 0.5
                if abs(nivel_barrido - ce) < atr14 * 0.5:
                    hay_fvg = True
                    break

        if hay_fvg:
            confluencias += 1
            sig.filtros_pasados.append("confluencia_fvg")
        else:
            sig.filtros_fallados.append("confluencia_fvg")

        hay_ob = False
        for i in range(2, 5):
            oi = ctx._i_open(ctx.df_m15, i)
            ci = ctx._i_close(ctx.df_m15, i)
            hi = ctx._i_high(ctx.df_m15, i)
            li = ctx._i_low(ctx.df_m15, i)
            ri = hi - li
            if ri <= 0 or hi == 0 or li == 0:
                continue
            if abs(ci - oi) / ri < ctx.inp_ob_body_min:
                continue
            nc = ctx._i_close(ctx.df_m15, i - 1)
            imp = abs(nc - ci) / atr14
            if imp < ctx.inp_ob_impulse_min:
                continue
            if abs(nivel_barrido - (hi + li) / 2.0) < atr14 * 0.5:
                hay_ob = True
                break
        if hay_ob:
            confluencias += 1
            sig.filtros_pasados.append("confluencia_ob")
        else:
            sig.filtros_fallados.append("confluencia_ob")

        hay_mss = False
        ok_mss, mss_bars, mss_dir, mss_level = ctx.detect_mss_h4()
        if ok_mss:
            md = 1 if mss_dir == "ALCISTA" else -1
            if md == sweep_dir:
                hay_mss = True
                confluencias += 1
                sig.filtros_pasados.append("confluencia_mss")
            else:
                sig.filtros_fallados.append("confluencia_mss")
        else:
            sig.filtros_fallados.append("confluencia_mss")

        sig.filtro_confluencias = confluencias
        sig._confluencias = confluencias
        sig.sweep_volume_ratio = ctx.get_volume_ratio_cached(0, max(ctx.inp_n_ruptura, ctx.inp_sweep_n, ctx.inp_ob_lookback, 10))

        # Campos observacionales estimados
        sig.velocidad_aproximacion = 50.0
        sig.toques_nivel = self._contar_toques_nivel(ctx, nivel_barrido, sweep_dir)

        sig.tipo = self.clasificar(sig, ctx)
        return sig

    def clasificar(self, sig: Signal, ctx: Contexto) -> str:
        wick = sig.sweep_wick_ratio
        vol = sig.sweep_volume_ratio
        confluencias = getattr(sig, '_confluencias', 2)
        if confluencias >= 3 and wick > 0.65 and vol > 1.50:
            return "A"
        if confluencias >= 2 and wick > 0.55 and vol > 1.20:
            return "B"
        if confluencias >= 2:
            return "C"
        return "D"

    def _contar_toques_nivel(self, ctx: Contexto, nivel: float, direction: int) -> int:
        if ctx.df_m15 is None:
            return 0
        atr14 = ctx.g_atr14_buffer[0] if ctx.g_atr14_buffer else 0.0
        if atr14 <= 0:
            return 0
        tol = ctx.inp_equal_hl_tol * atr14
        toques = 0
        for i in range(1, ctx.inp_equal_hl_window + 1):
            if i >= len(ctx.df_m15):
                break
            if direction == -1:
                h = ctx._i_high(ctx.df_m15, i)
                if h > 0 and abs(h - nivel) <= tol:
                    toques += 1
            else:
                l = ctx._i_low(ctx.df_m15, i)
                if l > 0 and abs(l - nivel) <= tol:
                    toques += 1
        return toques
