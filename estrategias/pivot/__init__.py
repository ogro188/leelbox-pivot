# -*- coding: utf-8 -*-
"""
Estrategia PIVOT - Estrategia principal basada en detectores D0-D5.
Sin restricciones: cada detector que dispare genera su propia señal independiente.
El sistema es un asistente. El operador decide. Los detectores informan, no bloquean.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

from kernel.contrato import Estrategia, Contexto, Señal, ActivoInfo, Overlay
from kernel.core_adapter import (
    CoreAdapter,
    actualizar_contexto_con_indicadores,
    aplicar_parametros,
)

# Importar detectores del core
from core.d1_ruptura import DetectorD1
from core.d2_sweep import DetectorD2
from core.d2_anticipacion import DetectorD2Anticipacion
from core.d3_fvg import DetectorD3
from core.d4_orderblock import DetectorD4
from core.d5_mss_sweep import DetectorD5
from core.scoring import ScoringEngine
from core.hipotesis import generar_hipotesis

# Campos del Signal del core que se exponen en contexto["detector_data"]
_DETECTOR_DATA_FIELDS = [
    "nivel_estructural", "range_break_pips", "br", "bs",
    "sweep_wick_ratio", "sweep_volume_ratio", "reclaim_body_ratio",
    "sweep_bars_ago", "equal_hl_detected", "level_swept",
    "fvg_size_pips", "fvg_size_atr", "fvg_mitigated", "fvg_top", "fvg_bottom",
    "ob_high", "ob_low", "ob_bars_ago", "ob_impulse_atr", "ob_confluence",
    "mss_aligned", "mss_bars_ago_h4", "mss_direction", "mss_level",
    "atr14", "calidad_sweep", "calidad_mss", "calidad_fvg", "calidad_ob",
    "salud_tendencial", "conf_sweep_fvg", "conf_completa",
    "contexto_estructural", "distancia_al_sweep", "en_zona_estructural",
    "estructura_direccion", "velocidad_aproximacion", "toques_nivel",
    "displacement_post_sweep",
]


@dataclass
class ConfiguracionPivot:
    """Configuración de la estrategia Pivot (sin filtros bloqueantes)."""
    # Profundidad de pivots (D0)
    pivot_depth: int = 2
    pivot_lookback: int = 24
    sweep_distancia: float = 1.5
    zona_margen: float = 0.5
    peso_estructural: float = 0.25

    # Umbrales de ruptura (D1)
    n_ruptura: int = 4
    d1_atr_threshold: float = 0.50
    body_ratio_min: float = 0.40
    use_retest: bool = True
    use_volume: bool = True
    min_volume: float = 1.2

    # Sweeps (D2)
    sweep_n: int = 6
    sweep_wick_min: float = 0.55
    reclaim_body_min: float = 0.55
    equal_hl_window: int = 10
    equal_hl_tol: float = 0.15
    d2_anticipar: bool = True

    # FVG (D3)
    fvg_min_size_atr: float = 0.20
    fvg_body_ratio: float = 0.55
    fvg_mitig_umbral: float = 0.50

    # Order Blocks (D4)
    ob_lookback: int = 12
    ob_body_min: float = 0.40
    ob_impulse_min: float = 0.70

    # MSS (D5)
    mss_lookback_h4: int = 20
    mss_max_age_h4_bars: int = 12

    # Gestión de riesgo
    risk_por_operacion: float = 1.0  # % del capital
    reward_ratio_min: float = 1.5    # R:R mínimo
    expiracion_velas: int = 4


class EstrategiaPivot(Estrategia):
    """
    Estrategia PIVOT principal.

    Combina los detectores D0-D5 del core:
    - D0: Estructura de mercado (pivots, zona de interés)
    - D1: Rupturas de rango con volumen
    - D2: Sweeps de liquidez con reclaim
    - D3: Fair Value Gaps (FVG)
    - D4: Order Blocks institucionales
    - D5: MSS (Market Structure Shift) con sweep

    Filosofía "sin restricciones":
    1. Cada detector que dispare genera SU PROPIA señal (sin agregación).
    2. La clasificación A/B/C/D informa, no filtra.
    3. La tendencia D1, sesión y kill zone son metadatos, no filtros.
    4. La confianza (hipótesis) se calcula y muestra, nunca bloquea.
    """

    nombre = "PIVOT"
    version = "1.0.0"
    timeframes = ["M15", "H1", "H4", "D1"]
    eventos = ["candle_close"]

    parametros = {
        # Estructura D0
        "pivot_depth": {"tipo": "int", "default": 2, "min": 1, "max": 5, "descripcion": "Profundidad del pivot"},
        "pivot_lookback": {"tipo": "int", "default": 24, "min": 10, "max": 50, "descripcion": "Ventana de búsqueda"},
        "sweep_distancia": {"tipo": "float", "default": 1.5, "min": 0.5, "max": 3.0, "descripcion": "Distancia al sweep maestro (x ATR)"},
        "zona_margen": {"tipo": "float", "default": 0.5, "min": 0.1, "max": 1.5, "descripcion": "Margen de la zona de interés (x ATR)"},
        "peso_estructural": {"tipo": "float", "default": 0.25, "min": 0.0, "max": 0.5, "descripcion": "Peso de estructura en scoring"},

        # D1
        "n_ruptura": {"tipo": "int", "default": 4, "min": 2, "max": 10},
        "d1_atr_threshold": {"tipo": "float", "default": 0.50, "min": 0.1, "max": 2.0},
        "body_ratio_min": {"tipo": "float", "default": 0.40, "min": 0.1, "max": 0.9},
        "use_retest": {"tipo": "bool", "default": True},
        "use_volume": {"tipo": "bool", "default": True},
        "min_volume": {"tipo": "float", "default": 1.2, "min": 0.5, "max": 3.0},

        # D2
        "sweep_n": {"tipo": "int", "default": 6, "min": 2, "max": 15},
        "sweep_wick_min": {"tipo": "float", "default": 0.55, "min": 0.3, "max": 0.9},
        "reclaim_body_min": {"tipo": "float", "default": 0.55, "min": 0.3, "max": 0.9},
        "equal_hl_window": {"tipo": "int", "default": 10, "min": 3, "max": 25},
        "equal_hl_tol": {"tipo": "float", "default": 0.15, "min": 0.05, "max": 0.5},
        "d2_anticipar": {"tipo": "bool", "default": True},

        # D3
        "fvg_min_size_atr": {"tipo": "float", "default": 0.20, "min": 0.05, "max": 0.8},
        "fvg_body_ratio": {"tipo": "float", "default": 0.55, "min": 0.3, "max": 0.9},
        "fvg_mitig_umbral": {"tipo": "float", "default": 0.50, "min": 0.1, "max": 0.9},

        # D4
        "ob_lookback": {"tipo": "int", "default": 12, "min": 4, "max": 30},
        "ob_body_min": {"tipo": "float", "default": 0.40, "min": 0.2, "max": 0.9},
        "ob_impulse_min": {"tipo": "float", "default": 0.70, "min": 0.3, "max": 1.5},

        # D5
        "mss_lookback_h4": {"tipo": "int", "default": 20, "min": 10, "max": 50},
        "mss_max_age_h4_bars": {"tipo": "int", "default": 12, "min": 4, "max": 30},

        # Gestión
        "risk_por_operacion": {"tipo": "float", "default": 1.0, "min": 0.1, "max": 5.0},
        "reward_ratio_min": {"tipo": "float", "default": 1.5, "min": 1.0, "max": 5.0},
        "expiracion_velas": {"tipo": "int", "default": 4, "min": 1, "max": 20},

        # Scoring histórico (Tarea 6)
        "z_score": {"tipo": "float", "default": 1.96, "min": 1.0, "max": 3.0},
        "min_muestras": {"tipo": "int", "default": 30, "min": 1, "max": 200},

        # Alertas ntfy (solo modo en vivo; además requiere PIVOT_ALERTAS_LIVE=1)
        "ntfy_topic": {"tipo": "str", "default": ""},
        "alertas_habilitadas": {"tipo": "bool", "default": False},
    }

    def __init__(self):
        self.config: Optional[ConfiguracionPivot] = None
        self.adapter: Optional[CoreAdapter] = None
        self.activo_info: Optional[ActivoInfo] = None

        # Instanciar detectores
        self.detectores = {
            "D1": DetectorD1(),
            "D2": DetectorD2(),
            "D2_ANTICIPACION": DetectorD2Anticipacion(),
            "D3": DetectorD3(),
            "D4": DetectorD4(),
            "D5": DetectorD5(),
        }

    def setup(self, params: Dict[str, Any], activo: ActivoInfo) -> None:
        """Inicializa la estrategia con parámetros configurados."""
        self.activo_info = activo

        self.config = ConfiguracionPivot(
            pivot_depth=params.get("pivot_depth", 2),
            pivot_lookback=params.get("pivot_lookback", 24),
            sweep_distancia=params.get("sweep_distancia", 1.5),
            zona_margen=params.get("zona_margen", 0.5),
            peso_estructural=params.get("peso_estructural", 0.25),
            n_ruptura=params.get("n_ruptura", 4),
            d1_atr_threshold=params.get("d1_atr_threshold", 0.50),
            body_ratio_min=params.get("body_ratio_min", 0.40),
            use_retest=params.get("use_retest", True),
            use_volume=params.get("use_volume", True),
            min_volume=params.get("min_volume", 1.2),
            sweep_n=params.get("sweep_n", 6),
            sweep_wick_min=params.get("sweep_wick_min", 0.55),
            reclaim_body_min=params.get("reclaim_body_min", 0.55),
            equal_hl_window=params.get("equal_hl_window", 10),
            equal_hl_tol=params.get("equal_hl_tol", 0.15),
            d2_anticipar=params.get("d2_anticipar", True),
            fvg_min_size_atr=params.get("fvg_min_size_atr", 0.20),
            fvg_body_ratio=params.get("fvg_body_ratio", 0.55),
            fvg_mitig_umbral=params.get("fvg_mitig_umbral", 0.50),
            ob_lookback=params.get("ob_lookback", 12),
            ob_body_min=params.get("ob_body_min", 0.40),
            ob_impulse_min=params.get("ob_impulse_min", 0.70),
            mss_lookback_h4=params.get("mss_lookback_h4", 20),
            mss_max_age_h4_bars=params.get("mss_max_age_h4_bars", 12),
            risk_por_operacion=params.get("risk_por_operacion", 1.0),
            reward_ratio_min=params.get("reward_ratio_min", 1.5),
            expiracion_velas=params.get("expiracion_velas", 4),
        )

        self.adapter = CoreAdapter()

        # Inicializar WilsonScorer por instancia (Tarea 6)
        from estrategias.pivot.scoring import WilsonScorer
        self.scorer = WilsonScorer(
            z_score=params.get("z_score", 1.96),
            min_muestras=params.get("min_muestras", 5),  # REDUCIDO: 5 para modo binary rápido
            modo=params.get("modo", "binary")  # "standard" o "binary"
        )
        self._cargar_historial_scoring()

        # Inicializar AlertasEngine (solo modo en vivo; desactivado en backtest)
        self.alertas_habilitadas = bool(params.get("alertas_habilitadas", False))
        try:
            from core.alertas import AlertasEngine
            self.alertas = AlertasEngine(
                symbol=activo.simbolo if activo else "EURUSD",
                ntfy_topic=params.get("ntfy_topic", "") or ""
            )
        except Exception as e:
            logger.error(f"AlertasEngine no disponible, alertas desactivadas: {e}", exc_info=True)
            self.alertas = None

    def detectar(self, ctx: Contexto) -> List[Señal]:
        """
        Evalúa el contexto actual y genera una señal por cada detector que dispare.

        Flujo:
        1. Actualizar indicadores (buffers de tamaño fijo)
        2. Adaptar contexto kernel -> core
        3. Aplicar todos los parámetros inp_*
        4. Ejecutar detectores D1-D5 (D0 solo provee estructura)
        5. Enriquecer cada Signal con scoring + hipótesis
        6. Convertir cada Signal en una kernel.Señal independiente
        """
        if not self.config or not self.adapter:
            return []

        # 1. Actualizar indicadores
        actualizar_contexto_con_indicadores(ctx, "M15")

        # 2. Adaptar contexto
        try:
            core_ctx = self.adapter.adaptar_contexto(ctx)
        except Exception as e:
            logger.error(f"[PIVOT] Error adaptando contexto: {e}", exc_info=True)
            return []

        # 3. Aplicar parámetros al contexto del core
        aplicar_parametros(core_ctx, self.config)

        # 4. Estructura D0 (contexto, no filtro)
        estructura = self.adapter.obtener_estructura()
        if estructura is None:
            # generar_hipotesis y el scoring esperan siempre un EstructuraRef válido
            from core.estructuras import EstructuraRef
            estructura = EstructuraRef()

        # 5. Ejecutar detectores (cada uno con su propia clasificación A/B/C/D)
        resultados = self.adapter.ejecutar_detectores(list(self.detectores.values()))

        # Recolectar las señales reales devueltas por los detectores
        candidatas = []
        for det_nombre, res in resultados.items():
            if isinstance(res, dict) and "error" in res:
                logger.error(f"Detector {det_nombre} devolvió error: {res['error']}")
            if isinstance(res, dict) and "senal" in res:
                candidatas.append(res["senal"])

        # 6. Enriquecer con scoring + hipótesis
        self._enriquecer_señales(core_ctx, ctx, candidatas, estructura)

        # 7. Una señal por detector
        señales = []
        for sig in candidatas:
            señal = self._construir_señal(ctx, sig, estructura)
            if señal is not None:
                señales.append(señal)

        # Alertas con datos reales (solo modo en vivo)
        if self.alertas is not None and getattr(self, "alertas_habilitadas", False):
            for sig in candidatas:
                try:
                    self.alertas.queue_alert(self.alertas.build_alert_text(sig))
                except Exception as e:
                    logger.error(f"Error encolando alerta: {e}", exc_info=True)

        return señales

    def _enriquecer_señales(self, core_ctx, kernel_ctx, candidatas, estructura):
        """Aplica scoring cruzado e hipótesis a cada Signal (igual que el motor v8)."""
        if not candidatas:
            return

        scoring = ScoringEngine(core_ctx)
        trend_d1 = getattr(kernel_ctx, "trend_d1", None) or "NEUTRO"
        atr14_real = core_ctx.g_atr14_buffer[0] if core_ctx.g_atr14_buffer else 1.0

        fvg_ahora = any(s.detector in ("D3", "D3_DEF") for s in candidatas)
        fvg_size_max = max(
            (s.fvg_size_atr for s in candidatas if s.detector in ("D3", "D3_DEF")),
            default=0.0,
        )

        for sig in candidatas:
            # Calidades según detector
            if sig.detector in ("D2", "D2_ANTICIPACION", "D5"):
                sig.calidad_sweep = scoring.calcular_calidad_sweep(
                    sig.sweep_wick_ratio, sig.reclaim_body_ratio,
                    sig.sweep_volume_ratio, sig.sweep_bars_ago, sig.equal_hl_detected
                )
            if sig.detector == "D5":
                sig.calidad_mss = scoring.calcular_calidad_mss(
                    sig.sweep_wick_ratio, sig.reclaim_body_ratio, sig.mss_bars_ago_h4
                )
            if sig.detector in ("D3", "D3_DEF"):
                br_impulso = getattr(sig, "_fvg_br", 0.6)
                sig.calidad_fvg = scoring.calcular_calidad_fvg(
                    sig.fvg_size_atr, br_impulso, sig.fvg_mitigated
                )
            if sig.detector == "D4":
                ob_vol = getattr(sig, "_ob_volume_ratio", 1.0)
                sig.calidad_ob = scoring.calcular_calidad_ob(
                    sig.ob_impulse_atr, sig.ob_bars_ago, ob_vol
                )

            # Salud tendencial
            slope = 0.0
            if len(core_ctx.g_ema21_buffer) > 3 and atr14_real > 0:
                slope = (core_ctx.g_ema21_buffer[0] - core_ctx.g_ema21_buffer[3]) / atr14_real
            sig.salud_tendencial = scoring.calcular_salud_tendencial(
                scoring.get_trend_velas(), slope, trend_d1, sig.direction
            )

            # Contexto estructural
            key_level = (
                sig.nivel_estructural or sig.level_swept or sig.fvg_top
                or sig.ob_high or sig.entry_price
            )
            ctx_score, dist = core_ctx.evaluar_contexto_estructural(
                sig.direction, key_level, sig.detector, trend_d1
            )
            sig.contexto_estructural = ctx_score
            sig.distancia_al_sweep = dist
            sig.en_zona_estructural = bool(estructura and estructura.en_zona)
            sig.estructura_direccion = (
                getattr(estructura, "dir_estructura", "NEUTRO") if estructura else "NEUTRO"
            )

            # Métricas G (informativas)
            sig.g1_compresion = core_ctx.g1 or 0.0
            sig.g2_persistencia = core_ctx.g2 or 0.0
            sig.g3_eficiencia = core_ctx.g3 or 0.0
            sig.g4_agotamiento = core_ctx.g4 or 0.0

            # Confluencias
            if sig.detector in ("D2_ANTICIPACION", "D3", "D3_DEF", "D5"):
                if sig.detector in ("D2_ANTICIPACION", "D3", "D3_DEF"):
                    sig.conf_sweep_fvg = scoring.calcular_confluencia_sweep_fvg(
                        [], sig.direction, fvg_ahora, fvg_size_max
                    )
                sig.conf_completa = scoring.calcular_confluencia_completa(
                    [], sig.direction, fvg_ahora, fvg_size_max
                )

            # Hipótesis completa (causa, efecto, razón, invalidez, prob)
            generar_hipotesis(sig, core_ctx, estructura)

            # Convicción
            sig.conviccion = scoring.calcular_conviccion(sig)

    def _construir_señal(self, ctx: Contexto, sig, estructura) -> Optional[Señal]:
        """Convierte un core.Signal en una kernel.Señal independiente."""
        precio_actual = ctx.precio
        atr14 = ctx.g_atr14_buffer[0] if ctx.g_atr14_buffer else 0.0
        if atr14 <= 0 or precio_actual <= 0 or not sig.direction:
            return None

        direccion = sig.direction
        if direccion == 1:
            stop_loss = precio_actual - (atr14 * 1.5)
            take_profit = precio_actual + (atr14 * self.config.reward_ratio_min * 1.5)
        else:
            stop_loss = precio_actual + (atr14 * 1.5)
            take_profit = precio_actual - (atr14 * self.config.reward_ratio_min * 1.5)

        prob_min = getattr(sig, "hipotesis_prob_min", 0) or 0
        prob_max = getattr(sig, "hipotesis_prob_max", 0) or 0
        if prob_max < prob_min:
            prob_max = prob_min

        narrativa = self._construir_narrativa(sig)

        detector_data = {
            campo: getattr(sig, campo)
            for campo in _DETECTOR_DATA_FIELDS
            # None = no evaluable en esta vela (ej. fvg_mitigated en la vela de
            # formacion del gap): se omite para no presentar "False" como dato.
            if hasattr(sig, campo) and getattr(sig, campo) is not None
        }

        contexto = {
            "tipo": getattr(sig, "tipo", ""),
            "detector": getattr(sig, "detector", ""),
            "detectores": [getattr(sig, "detector", "")],
            "conviccion": getattr(sig, "conviccion", ""),
            "session": ctx.session or "",
            "kill_zone": ctx.kill_zone or "",
            "trend_d1": ctx.trend_d1 or "NEUTRO",
            "regimen_vol": ctx.regimen_vol or "NORMAL",
            "estructura": {
                "swing_high": getattr(estructura, "swing_high", 0) if estructura else 0,
                "swing_low": getattr(estructura, "swing_low", 0) if estructura else 0,
                "dir_estructura": getattr(estructura, "dir_estructura", "NEUTRO") if estructura else "NEUTRO",
                "en_zona": bool(getattr(estructura, "en_zona", False)) if estructura else False,
                "sweep_nivel": getattr(estructura, "sweep_nivel", 0) if estructura else 0,
            },
            "detector_data": detector_data,
        }

        señal = Señal(
            estrategia=self.nombre,
            simbolo=ctx.activo.simbolo if ctx.activo else "UNKNOWN",
            direccion=direccion,
            precio=precio_actual,
            tiempo=ctx.tiempo,
            etiqueta=f"PIVOT_{sig.detector}",
            stop_loss=stop_loss,
            take_profit=take_profit,
            expiracion_velas=self.config.expiracion_velas,
            confianza=(prob_min, prob_max),
            score=prob_min / 100.0 if prob_max > 0 else 0.5,
            narrativa=narrativa,
            contexto=contexto,
            overlays=self._crear_overlays(direccion, precio_actual, stop_loss, take_profit, ctx.tiempo, sig.detector),
            activa=True,
        )
        return señal

    def _construir_narrativa(self, sig) -> str:
        """Construye la narrativa a partir de la hipótesis real generada por el core."""
        partes = [
            ("Causa", getattr(sig, "hipotesis_causa", "")),
            ("Efecto", getattr(sig, "hipotesis_efecto", "")),
            ("Razón", getattr(sig, "hipotesis_razon", "")),
            ("Invalidación", getattr(sig, "hipotesis_invalidez", "")),
        ]
        texto = " | ".join(
            f"{clave}: {valor}" for clave, valor in partes if valor
        )
        return texto or f"Setup {getattr(sig, 'detector', '')}"

    def _crear_overlays(self, direccion, precio, stop_loss, take_profit, tiempo, detector) -> List[Overlay]:
        """Crea overlays para visualización en el chart."""
        overlays = [
            Overlay(
                tipo="marker",
                position="belowBar" if direccion == 1 else "aboveBar",
                shape="arrowUp" if direccion == 1 else "arrowDown",
                color="#00ff00" if direccion == 1 else "#ff0000",
                text=f"PIVOT_{detector}",
                price=precio,
                time=tiempo,
            )
        ]
        if stop_loss:
            overlays.append(Overlay(
                tipo="line",
                color="#ff0000",
                price=stop_loss,
                extend="right",
            ))
        if take_profit:
            overlays.append(Overlay(
                tipo="line",
                color="#00ff00",
                price=take_profit,
                extend="right",
            ))
        return overlays

    def _cargar_historial_scoring(self):
        """Carga historial de señales previas desde la base de datos (Tarea 6)."""
        try:
            from kernel.storage import get_database
            db = get_database()
            with db._lock:
                cursor = db._conn.execute(
                    "SELECT detectores_activos, direccion, fue_ganadora FROM signals_ml_dataset WHERE fue_ganadora IS NOT NULL LIMIT 500"
                )
                filas = cursor.fetchall()
                for fila in filas:
                    detectores_str = fila[0] if fila[0] else ""
                    if detectores_str:
                        import json
                        try:
                            detectores = json.loads(detectores_str) if detectores_str.startswith('[') else detectores_str.split(',')
                        except Exception:
                            detectores = detectores_str.split(',')
                    else:
                        continue
                    direccion = fila[1]
                    resultado = fila[2] == 1
                    self.scorer.registrar_resultado(detectores, direccion, resultado)
        except Exception as e:
            logger.warning(f"No se pudo cargar historial de scoring (se empieza fresco): {e}")

    def on_backtest_tick(self, ctx: Contexto, operacion_abierta: bool) -> List[Señal]:
        """Hook especial para backtesting (opcional)."""
        return self.detectar(ctx)
