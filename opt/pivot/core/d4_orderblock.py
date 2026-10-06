#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D4 — Order Block confluence (intravela). Filtros informacionales."""
from core.estructuras import Signal
from core.base import Contexto, Detector


class DetectorD4(Detector):
    nombre = "D4"

    def detectar(self, ctx: Contexto) -> Signal:
        close0 = ctx._i_close(ctx.df_m15, 0)
        if close0 == 0:
            return None
        atr14 = ctx.g_atr14_buffer[0] if ctx.g_atr14_buffer else 0.0
        if atr14 <= 0:
            return None

        ob_bar = -1
        ob_dir = 0
        ob_high = 0.0
        ob_low = 0.0
        ob_impulse = 0.0
        ob_vol = 0.0
        ob_tested = False
        ob_body_ok = False
        ob_impulse_ok = False
        ob_impulse_dir_ok = False

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
            ob_body_ok = True
            di = 1 if ci > oi else -1
            nc = ctx._i_close(ctx.df_m15, i - 1)
            imp = abs(nc - ci) / atr14
            imp_dir_ok = (di == -1 and nc > ci) or (di == 1 and nc < ci)
            if imp < ctx.inp_ob_impulse_min or not imp_dir_ok:
                continue
            ob_impulse_ok = True
            ob_impulse_dir_ok = True

            tested = False
            for j in range(i - 1, 0, -1):
                hj = ctx._i_high(ctx.df_m15, j)
                lj = ctx._i_low(ctx.df_m15, j)
                if hj == 0 or lj == 0:
                    break
                if hj >= li and lj <= hi:
                    tested = True
                    break
            if tested:
                ob_tested = True
                continue

            ob_bar = i
            # Direccion = la del IMPULSO, no el color de la vela origen
            # (convencion estandar de order block). imp_dir_ok exige que el
            # impulso sea contrario al color de la vela candidata, por lo que
            # la direccion de la senal es -di.
            ob_dir = -di
            ob_high = hi
            ob_low = li
            ob_impulse = imp
            ob_vol = ctx.get_volume_ratio(i, ctx.inp_ob_lookback)
            break

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
        sig.regimen_volatilidad = ctx.regimen_vol

        if ob_bar == -1 or ob_bar > 4:
            sig.direction = 0
            sig.filtros_fallados.append("sin_ob_valido")
            sig.tipo = "D"
            return sig

        sig.direction = ob_dir
        sig.ob_high = ob_high
        sig.ob_low = ob_low
        sig.ob_bars_ago = ob_bar
        sig.ob_impulse_atr = ob_impulse
        sig._ob_volume_ratio = ob_vol
        sig.ob_confluence = True

        # Filtros informacionales
        sig.filtro_ob_body_ratio = abs(ctx._i_close(ctx.df_m15, ob_bar) - ctx._i_open(ctx.df_m15, ob_bar)) / (ctx._i_high(ctx.df_m15, ob_bar) - ctx._i_low(ctx.df_m15, ob_bar)) if (ctx._i_high(ctx.df_m15, ob_bar) - ctx._i_low(ctx.df_m15, ob_bar)) > 0 else 0
        if ob_body_ok:
            sig.filtros_pasados.append("ob_body_ratio")
        else:
            sig.filtros_fallados.append("ob_body_ratio")

        sig.filtro_ob_impulse = ob_impulse
        if ob_impulse_ok:
            sig.filtros_pasados.append("ob_impulse")
        else:
            sig.filtros_fallados.append("ob_impulse")

        sig.filtro_ob_tested = ob_tested
        if not ob_tested:
            sig.filtros_pasados.append("ob_no_tested")
        else:
            sig.filtros_fallados.append("ob_tested")

        entering = (ob_dir == 1 and close0 <= ob_high and close0 >= ob_low) or \
                    (ob_dir == -1 and close0 >= ob_low and close0 <= ob_high)
        sig.filtro_ob_entering = entering
        if entering:
            sig.filtros_pasados.append("ob_entering")
        else:
            sig.filtros_fallados.append("ob_entering")

        centro = (ob_high + ob_low) / 2.0
        dist_centro = abs(close0 - centro) / atr14 if atr14 > 0 else 0
        sig.filtro_ob_distancia = dist_centro
        if dist_centro <= 2.0:
            sig.filtros_pasados.append("ob_distancia")
        else:
            sig.filtros_fallados.append("ob_distancia")

        sig.tipo = self.clasificar(sig, ctx, ob_impulse, ob_vol, ob_bar)
        return sig

    def clasificar(self, sig: Signal, ctx: Contexto, impulso: float = None, vol: float = None, ob_bars: int = None) -> str:
        if impulso is None:
            impulso = sig.ob_impulse_atr
        if vol is None:
            vol = getattr(sig, '_ob_volume_ratio', 1.0)
        if ob_bars is None:
            ob_bars = sig.ob_bars_ago
        if impulso > 1.80 and vol > 1.50 and ob_bars <= 6:
            return "A"
        if impulso > 1.40 and vol > 1.20:
            return "B"
        if impulso >= ctx.inp_ob_impulse_min:
            return "C"
        return "D"
