# FASE 7.1 COMPLETADA - ID Único para Señales sin Colisiones

## Problema Resuelto (G7.1)

El sistema anterior generaba IDs de señales como:
```
PIVOT_EURUSD_20240615_1030
```

Esto causaba colisiones cuando:
- Mismo minuto, misma estrategia, mismo activo pero diferente dirección (LONG vs SHORT)
- Mismo minuto, mismos parámetros pero diferentes detectores activados

## Solución Implementada

Nuevo formato de ID con hash MD5 corto:
```
PIVOT_EURUSD_20240615_1030_a1b2c3
```

Donde el hash se calcula sobre:
- Estrategia
- Símbolo/Activo
- Timestamp (minuto)
- **Detectores activos** (ordenados alfabéticamente)
- **Dirección** (1 o -1)

### Código en `kernel/contrato.py`

```python
def __post_init__(self):
    if self.id_señal is None:
        import hashlib
        
        # Obtener detectores de contexto o atributo directo
        detectores_list = getattr(self, 'detectores', [])
        if not detectores_list and hasattr(self, 'contexto'):
            detectores_list = self.contexto.get('detectores', [])
        
        # Crear string único
        detectores_str = "_".join(sorted([str(d) for d in detectores_list]))
        direccion = self.direccion if hasattr(self, 'direccion') else 0
        contenido = f"{self.estrategia}_{self.simbolo}_{self.tiempo:%Y%m%d_%H%M}_{detectores_str}_{direccion}"
        
        # Hash de 6 caracteres
        hash_suffix = hashlib.md5(contenido.encode()).hexdigest()[:6]
        self.id_señal = f"{self.estrategia}_{self.simbolo}_{self.tiempo:%Y%m%d_%H%M}_{hash_suffix}"
```

## Tests Verificados

```bash
$ pytest tests/unit/test_id_senal_collision.py -v
✅ test_id_unico_diferente_direccion PASSED
✅ test_id_unico_diferentes_detectores PASSED  
✅ test_id_mismos_parametros_iguales PASSED
```

## Impacto

- ✅ Elimina colisiones silenciosas en backtesting
- ✅ Permite múltiples señales por vela (LONG + SHORT simultáneos)
- ✅ Determinístico: mismos inputs = mismo ID
- ✅ Legible: mantiene timestamp humano + hash único

## Estado: ✅ COMPLETADO

Comando de verificación:
```bash
pytest tests/unit/test_id_senal_collision.py --cov=kernel.contrato
```

Fecha: $(date +%Y-%m-%d)
