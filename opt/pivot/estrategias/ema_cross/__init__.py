from estrategias.base import Estrategia, Contexto, Señal, Overlay


class EmaCrossStrategy(Estrategia):
    nombre = "ema_cross"
    version = "1.0"
    timeframes = ["M15"]
    eventos = ["candle_close"]

    parametros = {
        "ema_rapida": {"tipo": "int", "default": 21, "min": 5, "max": 100, "label": "EMA Rápida"},
        "ema_lenta": {"tipo": "int", "default": 50, "min": 10, "max": 200, "label": "EMA Lenta"},
    }

    def setup(self, params, activo):
        self.ema_rapida = params.get("ema_rapida", 21)
        self.ema_lenta = params.get("ema_lenta", 50)
        self.activo = activo
        self.prev_estado = 0

    def detectar(self, ctx: Contexto) -> list[Señal]:
        ema_r = ctx.indicador("M15", "EMA", {"periodo": self.ema_rapida, "source": "close"})
        ema_l = ctx.indicador("M15", "EMA", {"periodo": self.ema_lenta, "source": "close"})
        if len(ema_r) < 2 or len(ema_l) < 2:
            return []
        estado_actual = 1 if ema_r.iloc[-1] > ema_l.iloc[-1] else -1
        estado_prev = 1 if ema_r.iloc[-2] > ema_l.iloc[-2] else -1
        if estado_actual != estado_prev:
            self.prev_estado = estado_actual
            return [Señal(
                estrategia=self.nombre,
                simbolo=self.activo.simbolo,
                direccion=estado_actual,
                precio=ctx.precio,
                tiempo=ctx.tiempo,
                expiracion_velas=4,
                confianza=(55, 70),
                etiqueta="CROSS",
                narrativa=f"Cruce EMA{self.ema_rapida}/EMA{self.ema_lenta}",
                overlays=[Overlay(tipo="marker", position="aboveBar" if estado_actual == 1 else "belowBar",
                                 shape="arrowUp" if estado_actual == 1 else "arrowDown")]
            )]
        return []
