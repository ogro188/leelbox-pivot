# ESPECIFICACIÓN TÉCNICA
## PivotRadar v8 — Eliminación de Restricciones Bloqueantes en RADAR v2.0

**Versión:** 1.0  
**Fecha:** 2026-08-08  
**Autor:** Análisis técnico del sistema  
**Estado:** Aprobado para desarrollo

---

## 1. RESUMEN EJECUTIVO

El repositorio `https://github.com/ogro188/pivot.git` (RADAR v2.0) contiene una estrategia PIVOT que integra los detectores D0-D5 del motor PivotRadar v8, pero añade **filtros bloqueantes** y **bugs de integración** que impiden que el sistema funcione como el motor local original.

Esta especificación detalla los cambios necesarios para que la estrategia PIVOT en RADAR v2.0 se comporte **idénticamente** al motor PivotRadar v8 local: sin restricciones externas, sin penalizaciones por contexto, sin umbral de confianza mínimo, y con todos los detectores ejecutándose libremente.

**Principio rector:** *El sistema es un asistente. El operador decide. Los detectores informan, no bloquean.*

---

## 2. ESTADO ACTUAL vs. ESTADO DESEADO

### 2.1 Estado Actual (Repositorio RADAR v2.0)

| Aspecto | Comportamiento Actual | Problema |
|---------|----------------------|----------|
| **Filtrado de calidad** | Solo señales tipo **A** y **B** pasan (`clasificacion in ["A","B"]`) | Señales C y D se descartan silenciosamente |
| **Tendencia D1** | Penaliza -15 si la señal es contra-tendencia | Filtro externo bloqueante enmascarado como scoring |
| **Sesión OUT** | Penaliza -20 si `session == "OUT"` | Restricción temporal no deseada |
| **Confianza mínima** | `if confianza < confianza_minima: return []` | Umbral rígido que elimina señales débiles |
| **Múltiples detectores** | Requiere `len(detectores_activos) >= 1` para generar señal | Cada detector debería generar su propia señal individualmente |
| **Alertas** | Construye `core.Signal` con campos hardcodeados (`mss_aligned=True`, `displacement_post_sweep=True`) | Notificaciones con datos inventados, no reales |
| **Runtime** | Llama `self.estrategia.generar_señal()` | Método inexistente. Lanza `AttributeError` siempre |
| **CoreAdapter** | Referencia `kernel_ctx.g_d1_trend_buffer` y similares | Campos no existen en `kernel.contrato.Contexto`. Lanza `AttributeError` |
| **Buffers de indicadores** | Usa `append()` y `extend()` en cada tick | Buffers crecen infinitamente; corrompen los cálculos de ATR/EMA |

### 2.2 Estado Deseado (Idéntico a motor PivotRadar v8 local)

| Aspecto | Comportamiento Deseado |
|---------|----------------------|
| **Filtrado de calidad** | Todos los tipos **A, B, C, D** pasan. La calidad informa, no filtra. |
| **Tendencia D1** | Se incluye en la narrativa/contexto como dato informativo. No penaliza. |
| **Sesión / Kill Zone** | Se incluyen en la señal como metadatos. No penalizan ni bloquean. |
| **Confianza** | Se calcula y se muestra. Nunca bloquea la emisión de la señal. |
| **Detectores** | Cada detector (D1, D2, D2_ANT, D3, D4, D5) que dispare genera **su propia señal** independiente. |
| **Alertas** | Usan los datos reales del `Signal` generado por cada detector. Sin campos hardcodeados. |
| **Runtime** | Llama `self.estrategia.detectar()` (método definido en la ABC `Estrategia`). |
| **CoreAdapter** | Mapea solo los campos que existen en ambos contextos. Sin referencias fantasmas. |
| **Buffers** | Se asignan como listas completas en cada tick (índice 0 = más reciente). Tamaño fijo. |

---

## 3. CAMBIOS POR ARCHIVO

### 3.1 `estrategias/pivot/__init__.py`

**Objetivo:** Transformar la estrategia de "filtro bloqueante" a "asistente sin restricciones".

#### 3.1.1 Eliminar filtro de calidad A/B

**Línea actual:**
```python
detectores_activos = [k for k, v in resultados.items() if v.get("clasificacion") in ["A", "B"]]
```

**Cambio requerido:**
```python
detectores_activos = [k for k, v in resultados.items() if "senal" in v]
```

**Justificación:** El motor local clasifica como A/B/C/D pero nunca descarta C o D. Son señales válidas con menor probabilidad. El operador las ve y decide.

---

#### 3.1.2 Eliminar requisito de mínimo de detectores

**Línea actual:**
```python
if len(detectores_activos) < 1:
    return []
```

**Cambio requerido:** Eliminar el bloque `if` completamente. En su lugar, iterar sobre cada detector que haya disparado y generar **una señal por detector**.

**Justificación:** El motor local no agrega señales de múltiples detectores en una sola. Cada detector es independiente y genera su propia alerta.

---

#### 3.1.3 Eliminar penalización por tendencia D1

**Bloque actual:**
```python
if self.config.usar_trend_d1 and ctx.trend_d1 != "NEUTRO":
    if (direccion == 1 and ctx.trend_d1 == "ALCISTA") or \
       (direccion == -1 and ctx.trend_d1 == "BAJISTA"):
        confianza += 10
    else:
        confianza -= 15
```

**Cambio requerido:** Eliminar el bloque completo. Mantener `ctx.trend_d1` en el campo `contexto` de la señal para que el frontend lo muestre, pero que no afecte el score ni la emisión.

**Justificación:** El diseño original establece que la tendencia D1 es un ponderador interno del score, no un filtro externo bloqueante. Pullbacks contra-tendencia son oportunidades válidas con score reducido.

---

#### 3.1.4 Eliminar penalización por sesión OUT

**Bloque actual:**
```python
if self.config.usar_kill_zones and ctx.session == "OUT":
    confianza -= 20
```

**Cambio requerido:** Eliminar el bloque completo. Mantener `ctx.session` y `ctx.kill_zone` en la señal como metadatos informativos.

**Justificación:** El motor local no penaliza por sesión. La sesión aparece en la alerta como contexto, pero nunca bloquea.

---

#### 3.1.5 Eliminar umbral de confianza mínima bloqueante

**Línea actual:**
```python
if confianza < self.config.confianza_minima:
    return []
```

**Cambio requerido:** Eliminar el bloque completo. La confianza se calcula y se muestra en la señal, pero nunca impide que la señal se genere.

**Justificación:** El motor local emite señales tipo D con probabilidad 35%. Son datos para el operador, no basura.

---

#### 3.1.6 Eliminar construcción artificial de `core.Signal` para alertas

**Bloque actual:**
```python
sig = Signal()
sig.mss_aligned = True
sig.displacement_post_sweep = True
sig.toques_nivel = 2
# ... etc
```

**Cambio requerido:** Usar directamente el `Signal` retornado por cada detector (`resultado["senal"]`). Si se necesita enriquecer con hipótesis, usar `generar_hipotesis()` del módulo `core.hipotesis` sobre el `Signal` real.

**Justificación:** Los campos hardcodeados mienten en las notificaciones. El operador recibe datos falsos.

---

#### 3.1.7 Generar una señal por detector (no una señal agregada)

**Comportamiento actual:** Agrega todos los detectores activos en una sola señal con dirección mayoritaria.

**Comportamiento deseado:** Por cada detector que retorne `senal`, generar una instancia independiente de `kernel.contrato.Señal`.

**Mapeo de campos `core.Signal` → `kernel.Señal`:**

| `core.Signal` | `kernel.Señal` | Nota |
|---------------|----------------|------|
| `detector` | `etiqueta` | Ej: "D2", "D3_DEF" |
| `direction` | `direccion` | 1 = LONG, -1 = SHORT |
| `entry_price` | `precio` | |
| `entry_time` | `tiempo` | |
| `tipo` | `contexto["tipo"]` | A/B/C/D |
| `hipotesis_prob_min`, `hipotesis_prob_max` | `confianza` | Tupla `(min, max)` |
| `hipotesis_causa` + `hipotesis_efecto` + `hipotesis_razon` + `hipotesis_invalidez` | `narrativa` | Concatenar con separadores |
| `conviccion` | `contexto["conviccion"]` | "ALTA"/"MEDIA"/"BAJA" |
| `session` | `contexto["session"]` | |
| `kill_zone` | `contexto["kill_zone"]` | |
| `trend_d1` | `contexto["trend_d1"]` | |
| `regimen_volatilidad` | `contexto["regimen_vol"]` | |
| `mss_aligned`, `equal_hl_detected`, etc. | `contexto["detector_data"]` | Dict con campos específicos |

---

#### 3.1.8 Eliminar parámetros bloqueantes del schema

**Parámetros a eliminar del diccionario `parametros`:**
- `usar_kill_zones` (bool)
- `usar_trend_d1` (bool)
- `confianza_minima` (float)

**Justificación:** Si no hay filtros, no necesitan existir como parámetros configurables.

---

### 3.2 `kernel/core_adapter.py`

**Objetivo:** Corregir el mapeo entre `kernel.Contexto` y `core.Contexto` para que no lance `AttributeError` ni corrompa buffers.

#### 3.2.1 Eliminar referencias a campos inexistentes

**Líneas a eliminar:**
```python
core_ctx.g_d1_trend_buffer = kernel_ctx.g_d1_trend_buffer
core_ctx.g_h4_trend_buffer = kernel_ctx.g_h4_trend_buffer
core_ctx.g_volatilidad_buffer = kernel_ctx.g_volatilidad_buffer
core_ctx.g_zona_buffer = kernel_ctx.g_zona_buffer
```

**Justificación:** El `Contexto` del kernel (`kernel/contrato.py`) no define estos atributos. Son parte de `GMetrics` (dataclass separado). El `core.Contexto` tampoco los necesita; usa `trend_d1` (string) y `regimen_vol` (string) directamente.

---

#### 3.2.2 Corregir `actualizar_contexto_con_indicadores()`

**Comportamiento actual:**
```python
ctx.g_atr8_buffer.append(float(df['atr8'].iloc[-1]))
ctx.g_atr14_buffer.extend(indicadores.get('g_atr14_buffer', []))
```

**Comportamiento deseado:**
```python
# Asignar buffers completos, reemplazando los anteriores
ctx.g_atr8_buffer = to_buffer(df['atr8']) if 'atr8' in df.columns else indicadores['g_atr8_buffer']
ctx.g_atr14_buffer = to_buffer(df['atr14']) if 'atr14' in df.columns else indicadores['g_atr14_buffer']
# ... igual para g_atr30_buffer, g_ema21_buffer, g_ema50_buffer, g_rsi14_buffer
```

Donde `to_buffer(series)` convierte una `pd.Series` a `list[float]` con índice 0 = valor más reciente:
```python
def to_buffer(series: pd.Series) -> List[float]:
    return [float(x) if not pd.isna(x) else 0.0 for x in series.iloc[::-1].values]
```

**Justificación:** El motor local espera buffers de tamaño fijo donde `[0]` es el valor actual. `append()` y `extend()` acumulan valores históricos, corrompiendo los cálculos de ATR, EMA y RSI.

---

#### 3.2.3 Asegurar que `core.Contexto` reciba todos los parámetros `inp_*`

**Comportamiento actual:** La estrategia PIVOT setea parámetros manualmente después de adaptar:
```python
core_ctx.inp_pivot_depth = self.config.pivot_depth
# ... etc
```

**Comportamiento deseado:** El `CoreAdapter` debe copiar **todos** los parámetros `inp_*` del `kernel.Contexto` al `core.Contexto` durante la adaptación. Si el `kernel.Contexto` no los tiene, la estrategia debe pasarlos explícitamente.

**Lista completa de parámetros `inp_*` requeridos por los detectores:**
- `inp_n_ruptura`
- `inp_d1_atr_threshold`
- `inp_body_ratio_min`
- `inp_d1_use_retest`
- `inp_d1_use_volume`
- `inp_d1_min_volume`
- `inp_sweep_n`
- `inp_sweep_wick_min`
- `inp_reclaim_body_min`
- `inp_equal_hl_window`
- `inp_equal_hl_tol`
- `inp_d2_anticipar`
- `inp_fvg_min_size_atr`
- `inp_fvg_body_ratio`
- `inp_fvg_mitig_umbral`
- `inp_ob_lookback`
- `inp_ob_body_min`
- `inp_ob_impulse_min`
- `inp_mss_lookback_h4`
- `inp_mss_max_age_h4_bars`
- `inp_pivot_depth`
- `inp_pivot_lookback`
- `inp_sweep_distancia`
- `inp_zona_margen`
- `inp_peso_estructural`

---

### 3.3 `kernel/runtime.py`

**Objetivo:** Corregir la llamada al método de la estrategia para que el backtest y el runtime en vivo funcionen.

#### 3.3.1 Cambiar `generar_señal()` → `detectar()`

**Línea actual:**
```python
señal = self.estrategia.generar_señal(self.contexto)
```

**Cambio requerido:**
```python
señales = self.estrategia.detectar(self.contexto)
for señal in señales:
    # procesar cada señal individualmente
```

**Justificación:** La clase base abstracta `Estrategia` define `detectar()`, no `generar_señal()`. Ninguna estrategia implementa `generar_señal()`.

---

#### 3.3.2 Adaptar el procesamiento para múltiples señales

**Comportamiento actual:** Espera una sola señal.

**Comportamiento deseado:** Iterar sobre la lista de señales retornada por `detectar()`.

**Cambios en `_process_candle`:**
- Reemplazar `if señal and señal.confianza >= ...` por `for señal in señales:`
- Remover la validación de `confianza >= confianza_minima` (ya no existe en la estrategia)
- Cada señal se procesa independientemente: callback `on_signal`, persistencia en DB, etc.

---

### 3.4 `kernel/contrato.py` (cambios menores)

**Objetivo:** Asegurar compatibilidad de tipos entre `core.Signal` y `kernel.Señal`.

#### 3.4.1 Añadir campo `contexto` para datos de detector

El campo `contexto: Dict[str, Any]` ya existe en `Señal`. Verificar que se usa para almacenar:
- `tipo` (A/B/C/D)
- `detector` (D1, D2, etc.)
- `conviccion`
- `session`, `kill_zone`, `trend_d1`
- `regimen_vol`
- `detector_data` (dict con campos específicos del detector: `mss_aligned`, `equal_hl_detected`, `fvg_size_atr`, etc.)

No requiere cambios si `contexto` ya es `Dict[str, Any]`.

---

## 4. FLUJO DE EJECUCIÓN DESEADO

```
1. Runtime recibe nueva vela M15 (y opcionalmente H1, H4, D1)
2. Actualiza kernel.Contexto con DataFrames
3. Llama estrategia.detectar(ctx) → List[Señal]
4. Por cada detector que haya disparado:
   a. CoreAdapter adapta kernel.Contexto → core.Contexto
   b. Detector.detectar(core_ctx) → core.Signal (o None)
   c. ScoringEngine enriquece calidades
   d. generar_hipotesis() construye narrativa
   e. Se convierte core.Signal → kernel.Señal
   f. Se emite al frontend vía WebSocket
   g. Se persiste en SQLite
   h. Se encola alerta ntfy (solo en vivo, no en backtest)
5. Cada señal es independiente; no hay agregación ni filtrado
```

---

## 5. CRITERIOS DE ACEPTACIÓN

### 5.1 Funcionales

- [ ] Una señal tipo D generada por D1 en sesión ASIA con tendencia D1 contraria **debe emitirse** y aparecer en el frontend.
- [ ] Cada detector que dispare genera **exactamente una** señal por vela (deduplicación por latch/hash sigue funcionando).
- [ ] El campo `confianza` de `kernel.Señal` muestra el rango real `(prob_min, prob_max)` del motor, no un score artificial.
- [ ] La narrativa de la señal contiene la hipótesis completa (causa, efecto, razón, invalidez) generada por `generar_hipotesis()`.
- [ ] El backtest procesa todas las velas sin lanzar `AttributeError`.
- [ ] El runtime en vivo conecta a Deriv y emite señales en tiempo real.

### 5.2 No funcionales

- [ ] No hay parámetros `usar_kill_zones`, `usar_trend_d1`, `confianza_minima` en la configuración de la estrategia.
- [ ] Los buffers de indicadores no crecen de tamaño entre ticks.
- [ ] El `CoreAdapter` no lanza `AttributeError` por campos inexistentes.
- [ ] Las alertas ntfy usan datos reales del detector, no hardcodeados.

---

## 6. RIESGOS Y CONSIDERACIONES

### 6.1 Impacto en backtesting

**Riesgo:** Al eliminar filtros, el número de señales en backtest aumentará significativamente (incluyendo tipo C y D). Las métricas históricas de win rate, Sharpe, etc. cambiarán drásticamente y no serán comparables con versiones anteriores.

**Mitigación:** Documentar claramente que esta versión es "sin restricciones". Las métricas de backtest deben interpretarse como "todas las oportunidades detectadas", no como "operaciones recomendadas".

### 6.2 Ruido en alertas

**Riesgo:** Señales tipo D con 35% de probabilidad pueden saturar al operador.

**Mitigación:** El frontend puede filtrar visualmente por tipo/convicción. El motor nunca bloquea; la UI puede optar por no mostrar D por defecto, pero el dato existe.

### 6.3 Duplicación de alertas ntfy

**Riesgo:** En backtest masivo, las alertas ntfy pueden saturar el topic.

**Mitigación:** Desactivar `AlertasEngine` del core durante backtest. Usar solo en modo en vivo. El `AlertasEngine` del kernel ya tiene esta lógica; verificar que se respeta.

---

## 7. ANEXOS

### 7.1 Diferencia de filosofía: Motor local vs. Estrategia RADAR

| Motor PivotRadar v8 (local) | Estrategia PIVOT (RADAR actual) |
|-----------------------------|--------------------------------|
| Asistente: detecta todo, humano decide | Filtro: solo pasa lo "bueno" |
| Filtros internos al detector (existencia del patrón) | Filtros externos post-detección |
| Cada detector emite señal propia | Agrega detectores en señal única |
| Probabilidad informa, no bloquea | Confianza mínima bloquea |
| Scoring enriquece narrativa | Scoring penaliza/descarta |
| Persistencia en CSV propio | Persistencia en SQLite RADAR |

### 7.2 Archivos a modificar (resumen)

1. `estrategias/pivot/__init__.py` — Reescritura mayor (quitar filtros, generar señal por detector)
2. `kernel/core_adapter.py` — Corrección de mapeo y buffers
3. `kernel/runtime.py` — Cambio de método `generar_señal` → `detectar`
4. `kernel/contrato.py` — Verificación de campos (cambio menor o ninguno)

---

*Fin de la especificación*
