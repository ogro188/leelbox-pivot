"""
Tests para el módulo de Scoring con Wilson Score.
Verifica que el scoring estadístico reemplaza correctamente la fórmula lineal arbitraria.
"""

import pytest
from estrategias.pivot.scoring import (
    WilsonScorer,
    calcular_confianza_pivot,
    scorer_global
)


class TestWilsonScorer:
    """Tests para la clase WilsonScorer."""
    
    def test_wilson_score_con_muestra_grande(self):
        """Con muestra grande, Wilson Score debería acercarse al win rate real."""
        scorer = WilsonScorer(z_score=1.96, min_muestras=30)
        
        # 80 éxitos de 100 operaciones (win rate 80%)
        wilson = scorer.calcular_wilson_score(exitos=80, total=100)
        
        # Con muestra grande, Wilson LB debería ser cercano pero conservador
        assert 0.70 < wilson < 0.85
        assert wilson < 0.80  # Wilson LB siempre es menor que el win rate crudo
    
    def test_wilson_score_con_muestra_pequena(self):
        """Con muestra pequeña, Wilson Score penaliza fuertemente."""
        scorer = WilsonScorer(z_score=1.96, min_muestras=30)
        
        # 4 éxitos de 5 operaciones (win rate 80% pero muestra tiny)
        wilson = scorer.calcular_wilson_score(exitos=4, total=5)
        
        # Debería ser mucho menor que 80% por incertidumbre estadística
        assert wilson < 0.50
        print(f"Wilson con 4/5: {wilson:.4f} (vs 80% crudo)")
    
    def test_wilson_score_sin_datos(self):
        """Sin datos, retornar neutral 0.5."""
        scorer = WilsonScorer()
        wilson = scorer.calcular_wilson_score(exitos=0, total=0)
        assert wilson == 0.5
    
    def test_registro_y_actualizacion(self):
        """Verificar que registrar resultados actualiza el historial correctamente."""
        scorer = WilsonScorer(min_muestras=10)
        
        # Registrar 5 operaciones ganadoras
        for _ in range(5):
            scorer.registrar_resultado(["D2", "D5"], direccion=1, fue_ganadora=True)
        
        # Registrar 2 perdedoras
        for _ in range(2):
            scorer.registrar_resultado(["D2", "D5"], direccion=1, fue_ganadora=False)
        
        confianza, explicacion = scorer.obtener_confianza(["D2", "D5"], direccion=1)
        
        # 5/7 = 71.4% win rate crudo, pero con penalización por muestra < 10
        assert "Muestra pequeña" in explicacion
        assert confianza < 71.4  # Penalizado por muestra pequeña
        print(f"Confianza: {confianza}, Explicación: {explicacion}")
    
    def test_hash_combinacion_orden_no_importa(self):
        """El orden de detectores no debería afectar el hash."""
        scorer = WilsonScorer()
        
        hash1 = scorer._generar_hash_combinacion(["D2", "D5", "D1"], direccion=1)
        hash2 = scorer._generar_hash_combinacion(["D1", "D5", "D2"], direccion=1)
        
        assert hash1 == hash2
        assert hash1 == "D1,D2,D5_LONG"
    
    def test_diferenciacion_por_direccion(self):
        """La misma combinación en LONG y SHORT debe tener hashes distintos."""
        scorer = WilsonScorer()
        
        hash_long = scorer._generar_hash_combinacion(["D2", "D5"], direccion=1)
        hash_short = scorer._generar_hash_combinacion(["D2", "D5"], direccion=-1)
        
        assert hash_long != hash_short
        assert hash_long.endswith("_LONG")
        assert hash_short.endswith("_SHORT")
    
    def test_exportar_estadisticas(self):
        """Verificar formato de exportación de estadísticas."""
        scorer = WilsonScorer(min_muestras=5)
        
        # Agregar algunas operaciones
        scorer.registrar_resultado(["D1", "D2"], 1, True)
        scorer.registrar_resultado(["D1", "D2"], 1, False)
        scorer.registrar_resultado(["D1", "D2"], 1, True)
        
        stats = scorer.exportar_estadisticas()
        
        assert len(stats) == 1
        stat = stats[0]
        
        assert stat["combinacion"] == "D1,D2_LONG"
        assert stat["total_operaciones"] == 3
        assert stat["ganadoras"] == 2
        assert stat["perdedoras"] == 1
        assert abs(stat["win_rate_crudo"] - 0.6667) < 0.001
        assert "wilson_score_lb" in stat
        assert "muestra_suficiente" in stat
        assert stat["muestra_suficiente"] is False  # 3 < 5


class TestFuncionPrincipal:
    """Tests para la función calcular_confianza_pivot."""
    
    def test_primera_senal_sin_historial(self):
        """Primera señal sin historial debe dar confianza neutral ~50%."""
        # Resetear scorer global para test limpio
        scorer_global.historial.clear()
        
        confianza, explicacion = calcular_confianza_pivot(
            detectores_activos=["D2", "D5"],
            direccion=1,
            resultado_operacion=None
        )
        
        assert confianza == 50.0
        assert "Sin historial" in explicacion
    
    def test_registrar_resultado_actualiza_confianza(self):
        """Registrar resultados debería actualizar la confianza para futuras señales."""
        scorer_global.historial.clear()
        
        # Simular 10 operaciones con D2+D5 LONG
        for i in range(10):
            # Registrar resultado anterior
            if i > 0:
                calcular_confianza_pivot(
                    detectores_activos=["D2", "D5"],
                    direccion=1,
                    resultado_operacion=(i % 2 == 0)  # Alternar ganar/perder
                )
            
            # Obtener confianza actual
            confianza, _ = calcular_confianza_pivot(
                detectores_activos=["D2", "D5"],
                direccion=1,
                resultado_operacion=None
            )
        
        # Después de varias operaciones, ya no debería ser 50%
        assert confianza != 50.0
        print(f"Confianza después de 10 ops: {confianza}")
    
    def test_combinaciones_distintas_independientes(self):
        """Diferentes combinaciones de detectores deben tener historiales separados."""
        scorer_global.historial.clear()
        
        # Operaciones con D1+D2
        calcular_confianza_pivot(["D1", "D2"], 1, resultado_operacion=True)
        calcular_confianza_pivot(["D1", "D2"], 1, resultado_operacion=True)
        
        # Operaciones con D5 solo
        calcular_confianza_pivot(["D5"], 1, resultado_operacion=False)
        
        # Verificar que hay 2 combinaciones distintas
        assert len(scorer_global.historial) == 2
        
        confianza_d1d2, exp1 = calcular_confianza_pivot(["D1", "D2"], 1)
        confianza_d5, exp2 = calcular_confianza_pivot(["D5"], 1)
        
        # Deberían ser diferentes
        assert confianza_d1d2 != confianza_d5
        print(f"D1+D2: {confianza_d1d2} ({exp1})")
        print(f"D5 solo: {confianza_d5} ({exp2})")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
