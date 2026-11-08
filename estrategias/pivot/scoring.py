"""
Módulo de Scoring Estadístico para Estrategia PIVOT
Implementa Wilson Score Lower Bound para confianza honesta con muestras pequeñas.
Reemplaza la fórmula lineal arbitraria: confianza = len(detectores) * 20
"""

import math
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class HistorialCombinacion:
    """Registro histórico de una combinación específica de detectores."""
    combinacion_hash: str
    total_operaciones: int = 0
    operaciones_ganadoras: int = 0
    
    @property
    def win_rate(self) -> float:
        if self.total_operaciones == 0:
            return 0.5
        return self.operaciones_ganadoras / self.total_operaciones


class WilsonScorer:
    """
    Calcula confianza usando Wilson Score Lower Bound.
    
    Fórmula:
    confidence = (p + z²/(2n) - z * sqrt((p*(1-p) + z²/(4n))/n)) / (1 + z²/n)
    
    Donde:
    - p = proporción de éxitos (win_rate)
    - n = tamaño de muestra (total_operaciones)
    - z = z-score para nivel de confianza (1.96 para 95%)
    
    Esto penaliza combinaciones con pocas operaciones, evitando sobreestimación.
    """
    
    def __init__(self, z_score: float = 1.96, min_muestras: int = 30, modo: str = "standard"):
        self.z_score = z_score  # 95% confidence
        self.min_muestras = min_muestras
        self.modo = modo  # "standard" o "binary"
        
        # Historial por combinación de detectores + dirección
        # Key: hash("D1,D2,D5_LONG")
        self.historial: Dict[str, HistorialCombinacion] = {}
    
    def _generar_hash_combinacion(self, detectores: List[str], direccion: int) -> str:
        """Genera hash único para una combinación de detectores y dirección."""
        detectores_ordenados = sorted(detectores)
        dir_str = "LONG" if direccion == 1 else "SHORT"
        return f"{','.join(detectores_ordenados)}_{dir_str}"
    
    def registrar_resultado(
        self, 
        detectores_activos: List[str], 
        direccion: int, 
        fue_ganadora: bool
    ) -> None:
        """Registra el resultado de una operación para actualizar estadísticas."""
        hash_key = self._generar_hash_combinacion(detectores_activos, direccion)
        
        if hash_key not in self.historial:
            self.historial[hash_key] = HistorialCombinacion(combinacion_hash=hash_key)
        
        hist = self.historial[hash_key]
        hist.total_operaciones += 1
        if fue_ganadora:
            hist.operaciones_ganadoras += 1
    
    def calcular_wilson_score(self, exitos: int, total: int) -> float:
        """
        Calcula Wilson Score Lower Bound.
        
        Args:
            exitos: Número de operaciones ganadoras
            total: Número total de operaciones
            
        Returns:
            Límite inferior del intervalo de confianza (0.0 a 1.0)
        """
        if total == 0:
            return 0.5  # Neutral sin datos
        
        p = exitos / total
        n = total
        z = self.z_score
        
        denominador = 1 + z**2 / n
        centro = p + z**2 / (2 * n)
        margen = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n)
        
        wilson_lower = (centro - margen) / denominador
        
        return max(0.0, min(1.0, wilson_lower))
    
    def obtener_confianza(
        self, 
        detectores_activos: List[str], 
        direccion: int
    ) -> tuple[float, str]:
        """
        Obtiene confianza calculada y explicación para una combinación.
        
        Returns:
            Tuple (confianza_0_100, explicacion)
        """
        hash_key = self._generar_hash_combinacion(detectores_activos, direccion)
        
        if hash_key not in self.historial:
            # Sin historial: confianza base moderada
            return 50.0, "Sin historial previo - confianza neutral"
        
        hist = self.historial[hash_key]
        
        # Calcular Wilson Score
        wilson = self.calcular_wilson_score(hist.operaciones_ganadoras, hist.total_operaciones)
        
        # Penalizar si hay pocas muestras
        if hist.total_operaciones < self.min_muestras:
            factor_penalizacion = hist.total_operaciones / self.min_muestras
            wilson_adjusted = wilson * factor_penalizacion
            explicacion = (
                f"Muestra pequeña ({hist.total_operaciones}/{self.min_muestras}). "
                f"Wilson: {wilson:.2f}, Ajustado: {wilson_adjusted:.2f}"
            )
        else:
            wilson_adjusted = wilson
            explicacion = (
                f"Muestra sólida ({hist.total_operaciones} ops). "
                f"WinRate: {hist.win_rate:.2f}, Wilson LB: {wilson:.2f}"
            )
        
        return round(wilson_adjusted * 100, 2), explicacion
    
    def exportar_estadisticas(self) -> List[Dict]:
        """Exporta todas las estadísticas para análisis externo."""
        resultados = []
        for hash_key, hist in self.historial.items():
            wilson = self.calcular_wilson_score(hist.operaciones_ganadoras, hist.total_operaciones)
            resultados.append({
                "combinacion": hash_key,
                "total_operaciones": hist.total_operaciones,
                "ganadoras": hist.operaciones_ganadoras,
                "perdedoras": hist.total_operaciones - hist.operaciones_ganadoras,
                "win_rate_crudo": round(hist.win_rate, 4),
                "wilson_score_lb": round(wilson, 4),
                "muestra_suficiente": hist.total_operaciones >= self.min_muestras
            })
        
        # Ordenar por cantidad de operaciones (más relevantes primero)
        return sorted(resultados, key=lambda x: x["total_operaciones"], reverse=True)


# Instancia global para usar en la estrategia
scorer_global = WilsonScorer(z_score=1.96, min_muestras=30)


def calcular_confianza_pivot(
    detectores_activos: List[str],
    direccion: int,
    resultado_operacion: Optional[bool] = None
) -> tuple[float, str]:
    """
    Función principal para calcular confianza de una señal PIVOT.
    
    Si se proporciona resultado_operacion, primero registra el resultado
    antes de calcular la nueva confianza.
    
    Args:
        detectores_activos: Lista de nombres de detectores que dispararon
        direccion: 1 para LONG, -1 para SHORT
        resultado_operacion: True si ganó, False si perdió, None si es nueva señal
        
    Returns:
        Tuple (confianza_0_100, explicacion)
    """
    # Registrar resultado si existe
    if resultado_operacion is not None and detectores_activos:
        scorer_global.registrar_resultado(detectores_activos, direccion, resultado_operacion)
    
    # Calcular confianza actual
    confianza, explicacion = scorer_global.obtener_confianza(detectores_activos, direccion)
    
    return confianza, explicacion
