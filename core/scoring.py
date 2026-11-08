#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scoring: métricas G, calidades, confluencias, salud tendencial."""
from core.estructuras import Signal
from core.base import Contexto
from core.utils import clamp_0_100


class ScoringEngine:
    """Toda la lógica de scoring que antes vivía en el motor monolítico."""

    def __init__(self, ctx: Contexto):
        self.ctx = ctx

    # =========================================================================
    # MÉTRICAS G
    # =========================================================================
    def calcular_g1_compresion(self) -> float:
        atr_now = self.ctx.g_atr14_buffer[0] if self.ctx.g_atr14_buffer else 0.0
        if atr_now <= 0:
            return 50.0
        # Usamos historial de ATR14 (no está en ctx, lo calculamos del buffer)
        s = 0.0
        count = 0
        for i in range(min(20, len(self.ctx.g_atr14_buffer))):
            if self.ctx.g_atr14_buffer[i] > 0:
                s += self.ctx.g_atr14_buffer[i]
                count += 1
        if count == 0:
            return 50.0
        avg = s / count
        if avg <= 0:
            return 50.0
        return clamp_0_100((1.5 - atr_now / avg) / 1.0 * 100.0)

    def calcular_g2_persistencia(self) -> float:
        up10, down10, up20, down20 = 0, 0, 0, 0
        for i in range(1, 21):
            ci = self.ctx._i_close(self.ctx.df_m15, i)
            oi = self.ctx._i_open(self.ctx.df_m15, i)
            up = ci > oi
            if i <= 10:
                if up:
                    up10 += 1
                else:
                    down10 += 1
            if up:
                up20 += 1
            else:
                down20 += 1
        d10 = max(up10, down10) / 10.0
        d20 = max(up20, down20) / 20.0
        return clamp_0_100(
            clamp_0_100((d10 - 0.5) / 0.5 * 100.0) * 0.6
            + clamp_0_100((d20 - 0.5) / 0.5 * 100.0) * 0.4
        )

    def calcular_g3_eficiencia(self) -> float:
        n = 10
        ini = self.ctx._i_close(self.ctx.df_m15, n)
        fin = self.ctx._i_close(self.ctx.df_m15, 0)
        neto = abs(fin - ini)
        total = 0.0
        for i in range(n):
            h = self.ctx._i_high(self.ctx.df_m15, i)
            l = self.ctx._i_low(self.ctx.df_m15, i)
            if h == 0 or l == 0:
                break
            total += h - l
        if total <= 0:
            return 50.0
        return clamp_0_100(neto / total * 100.0)

    def calcular_g4_agotamiento(self) -> float:
        n = 6
        m = n // 2
        mp, mu, cp, cu = 0.0, 0.0, 0.0, 0.0
        for i in range(n):
            o = self.ctx._i_open(self.ctx.df_m15, i)
            c = self.ctx._i_close(self.ctx.df_m15, i)
            h = self.ctx._i_high(self.ctx.df_m15, i)
            l = self.ctx._i_low(self.ctx.df_m15, i)
            if h == 0 or l == 0:
                break
            r = h - l
            if r <= 0:
                continue
            me = r - abs(c - o)
            cu2 = abs(c - o)
            if i < m:
                mu += me
                cu += cu2
            else:
                mp += me
                cp += cu2
        atr14 = self.ctx.g_atr14_buffer[0] if self.ctx.g_atr14_buffer else 0.0
        if atr14 <= 0:
            return 0.0
        score_mechas = ((mu - mp) / atr14) * 50.0
        score_cuerpos = ((cu - cp) / atr14) * 50.0
        return clamp_0_100(
            clamp_0_100(score_mechas) + clamp_0_100(score_cuerpos)
        )

    # =========================================================================
    # CALIDADES
    # =========================================================================
    def calcular_calidad_sweep(self, wick: float, reclaim: float, vol: float, bars_ago: int, equal_hl: bool) -> float:
        t = (
            clamp_0_100((wick - 0.55) / 0.45 * 40)
            + clamp_0_100((reclaim - 0.55) / 0.45 * 35)
            + clamp_0_100((6 - bars_ago) / 5.0 * 15)
            + clamp_0_100(min(vol, 2.0) / 2.0 * 10)
        )
        if equal_hl:
            t = min(100.0, t + 10)
        return clamp_0_100(t)

    def calcular_calidad_mss(self, wick: float, reclaim: float, mss_bars_ago: int) -> float:
        denom = max(self.ctx.inp_mss_max_age_h4_bars - 1, 1)
        return clamp_0_100(
            clamp_0_100((wick - 0.55) / 0.45 * 40)
            + clamp_0_100((self.ctx.inp_mss_max_age_h4_bars - mss_bars_ago) / denom * 30)
            + clamp_0_100((reclaim - 0.55) / 0.45 * 30)
        )

    def calcular_calidad_fvg(self, fvg_size: float, br_impulso: float, defendido: bool) -> float:
        denom1 = max(0.80 - self.ctx.inp_fvg_min_size_atr, 1e-9)
        denom2 = max(1.0 - self.ctx.inp_fvg_body_ratio, 1e-9)
        t = (
            clamp_0_100((fvg_size - self.ctx.inp_fvg_min_size_atr) / denom1 * 45)
            + clamp_0_100((br_impulso - self.ctx.inp_fvg_body_ratio) / denom2 * 35)
        )
        if defendido:
            t = min(100.0, t + 20)
        return clamp_0_100(t)

    def calcular_calidad_ob(self, impulso: float, ob_bars: int, vol: float) -> float:
        denom = max(self.ctx.inp_ob_lookback - 1, 1)
        return clamp_0_100(
            clamp_0_100((impulso - self.ctx.inp_ob_impulse_min) / (2.5 - self.ctx.inp_ob_impulse_min) * 50)
            + clamp_0_100((self.ctx.inp_ob_lookback - ob_bars) / denom * 30)
            + clamp_0_100(min(vol, 2.0) / 2.0 * 20)
        )

    def calcular_salud_tendencial(self, trend: int, slope: float, trend_d1: str, dir_sig: int) -> float:
        p3 = 0.0
        if (dir_sig == 1 and trend_d1 == "ALCISTA") or (dir_sig == -1 and trend_d1 == "BAJISTA"):
            p3 = 25.0
        return clamp_0_100(
            clamp_0_100(min(trend, 15) / 15.0 * 40)
            + clamp_0_100(min(abs(slope), 1.0) * 35)
            + p3
        )

    def get_trend_velas(self) -> int:
        if len(self.ctx.g_ema21_buffer) < 2 or len(self.ctx.g_ema50_buffer) < 2:
            return 0
        up = self.ctx.g_ema21_buffer[1] > self.ctx.g_ema50_buffer[1]
        down = self.ctx.g_ema21_buffer[1] < self.ctx.g_ema50_buffer[1]
        if not up and not down:
            return 0
        count = 0
        max_i = min(55, len(self.ctx.g_ema21_buffer), len(self.ctx.g_ema50_buffer))
        for i in range(1, max_i):
            u = self.ctx.g_ema21_buffer[i] > self.ctx.g_ema50_buffer[i]
            d = self.ctx.g_ema21_buffer[i] < self.ctx.g_ema50_buffer[i]
            if not u and not d:
                continue
            if up and not u:
                break
            if down and not d:
                break
            count += 1
        return count

    # =========================================================================
    # CONFLUENCIAS
    # =========================================================================
    def hubo_senal_reciente_en_direccion(self, pending_signals, det: str, dir_sig: int, n_velas: int) -> bool:
        for s in pending_signals:
            if s.detector != det or s.direction != dir_sig:
                continue
            a = s.entry_bar_shift
            if a >= 0 and a <= n_velas:
                return True
        return False

    def calcular_confluencia_sweep_fvg(self, pending_signals, dir_sig: int, fvg_ahora: bool, fvg_size: float) -> float:
        if not self.hubo_senal_reciente_en_direccion(pending_signals, "D2", dir_sig, 6):
            return 0.0
        if not fvg_ahora:
            return 40.0
        return clamp_0_100(60.0 + clamp_0_100((fvg_size - self.ctx.inp_fvg_min_size_atr) / 0.60 * 40) * 0.4)

    def calcular_confluencia_completa(self, pending_signals, dir_sig: int, fvg_ahora: bool, fvg_size: float) -> float:
        p = 0
        if self.hubo_senal_reciente_en_direccion(pending_signals, "D5", dir_sig, 8):
            p += 1
        if self.hubo_senal_reciente_en_direccion(pending_signals, "D2", dir_sig, 8):
            p += 1
        if fvg_ahora:
            p += 1
        if p == 0:
            return 0.0
        if p == 1:
            return 25.0
        if p == 2:
            return 60.0
        return clamp_0_100(85.0 + clamp_0_100((fvg_size - self.ctx.inp_fvg_min_size_atr) / 0.60 * 15) * 0.15)

    # =========================================================================
    # CONVICCIÓN
    # =========================================================================
    def calcular_conviccion(self, sig: Signal) -> str:
        confluencias = 0
        if sig.mss_aligned:
            confluencias += 1
        if sig.equal_hl_detected:
            confluencias += 1
        if sig.ob_confluence:
            confluencias += 1
        if sig.kill_zone != "NONE":
            confluencias += 1
        if sig.conf_completa >= 60:
            confluencias += 1
        if sig.contexto_estructural >= 70:
            confluencias += 1
        calidad_max = max(sig.calidad_sweep, sig.calidad_mss, sig.calidad_fvg, sig.calidad_ob)
        if calidad_max >= 70:
            confluencias += 1

        if confluencias >= 4:
            return "ALTA"
        elif confluencias >= 2:
            return "MEDIA"
        else:
            return "BAJA"
