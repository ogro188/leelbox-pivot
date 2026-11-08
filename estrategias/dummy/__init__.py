from estrategias.base import Estrategia, Contexto, Señal
from datetime import datetime
import random


class DummyStrategy(Estrategia):
    nombre = "dummy"
    version = "1.0"
    timeframes = ["M15"]
    eventos = ["candle_close"]

    parametros = {
        "frecuencia": {"tipo": "int", "default": 5, "min": 1, "max": 100,
                       "label": "Emitir cada N velas"}
    }

    def setup(self, params, activo):
        self.frecuencia = params.get("frecuencia", 5)
        self.contador = 0
        self.activo = activo

    def detectar(self, ctx: Contexto) -> list[Señal]:
        self.contador += 1
        if self.contador % self.frecuencia != 0:
            return []
        direccion = 1 if random.random() > 0.5 else -1
        return [Señal(
            estrategia=self.nombre,
            simbolo=self.activo.simbolo,
            direccion=direccion,
            precio=ctx.precio,
            tiempo=ctx.tiempo,
            expiracion_velas=4,
            confianza=(50, 60),
            etiqueta="DUMMY",
            narrativa=f"Señal dummy {self.contador}"
        )]
