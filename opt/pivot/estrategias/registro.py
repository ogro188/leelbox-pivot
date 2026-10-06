"""Registro dinámico de estrategias."""
import os
import sys
import importlib.util
from kernel.contrato import Estrategia


class RegistroEstrategias:
    def __init__(self, path: str = "estrategias"):
        self.path = path
        self._estrategias: dict[str, type[Estrategia]] = {}
        self._escanear()

    def _escanear(self) -> None:
        base = os.path.join(os.path.dirname(__file__), "..")
        full = os.path.join(base, self.path)
        if not os.path.isdir(full):
            return
        for name in os.listdir(full):
            init = os.path.join(full, name, "__init__.py")
            if os.path.isfile(init):
                spec = importlib.util.spec_from_file_location(f"estrategias.{name}", init)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = mod
                spec.loader.exec_module(mod)
                for attr in dir(mod):
                    obj = getattr(mod, attr)
                    if isinstance(obj, type) and issubclass(obj, Estrategia) and obj is not Estrategia:
                        self._estrategias[obj.nombre] = obj

    def listar(self) -> list[dict]:
        return [{"nombre": n, "version": c.version, 
                 "descripcion": getattr(c, "descripcion", ""),
                 "timeframes": c.timeframes, "parametros": c.parametros}
                for n, c in self._estrategias.items()]

    def fabricar(self, nombre: str) -> Estrategia:
        cls = self._estrategias.get(nombre)
        if not cls:
            raise ValueError(f"Estrategia no encontrada: {nombre}")
        return cls()

registro = RegistroEstrategias()
