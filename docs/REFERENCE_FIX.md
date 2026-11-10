# Corrección de referencias temporales y re-baseline

**Fecha:** 2026-11-09 UTC
**Estado:** shadow; producción intacta; sin promoción de candidatos.
**Motivo:** la auditoría interna detectó tres desfases de referencia entre producción, replay y alertas. Este documento registra qué se corrigió, qué cambió en los resultados y qué **no** cambió.

---

## 1. Resumen ejecutivo

Se corrigieron tres problemas independientes:

1. **Alerta:** mostraba la hora UTC de apertura de la vela, pero la sesión/kill zone se calculaban con offset UTC+2. Ahora muestra el cierre de la vela en UTC y la sesión coherente con ese instante.
2. **Entrada:** `entry_time` era la apertura de la vela, pero `entry_price` era su cierre. Se mantuvo `entry_time` para no romper IDs ni uniones, y se añadió `decision_time = entry_time + 15 min`, que es el instante real de decisión.
3. **Replay/backtest:** los timeframes H1/H4/D1 usaban la vela en formación con su OHLC completo, calculado con M15 posteriores al instante de decisión. Ahora se usa un contexto causal: velas superiores cerradas + bucket en formación agregado solo con M15 ya cerradas, igual que el runtime live.

Después de corregir, **el veredicto no cambia**: cero supervivientes FDR, holdout negativo y producción negativa. Las cifras se movieron poco, pero el baseline publicado queda libre de look-ahead en el contexto superior.

---

## 2. Los tres desfases

### 2.1 Hora de alerta vs sesión

**Antes**

- `core/alertas.py` imprimía `entry_time` (apertura de la vela) como hora UTC.
- `core/motor_v8.py` calculaba `session` y `kill_zone` con la misma apertura, pero interpretada en horario del broker (UTC+2).
- Resultado: la hora visible y la etiqueta de sesión podían diferir hasta 2 horas, y además la hora visible era 15 minutos anterior al cierre.

**Después**

- La alerta usa `sig.decision_time` (cierre) y muestra `⚡ HH:MM UTC · SESIÓN`.
- `session` y `kill_zone` se calculan en `decision_time`.
- Se añade, cuando el runtime tiene precio actual, una línea `PRECIO AL ENVIAR` con la deriva respecto de `entry_price`. Esto hace medible la latencia real sin tocar producción.

### 2.2 `entry_time` vs `entry_price`

**Antes**

- `entry_time` = apertura de la vela M15.
- `entry_price` = cierre de esa misma vela.
- La señal se emitía al cierre, pero la referencia temporal pública seguía siendo la apertura. Cualquier medición de latencia (`created_at − entry_time`) incluía 15 minutos de desfase estructural.

**Después**

- `entry_time` se conserva como apertura para no romper IDs, uniones con `senales_core` ni comparaciones con la producción existente.
- `Signal.decision_time` devuelve `entry_time + 15 min`.
- La alerta, la sesión y la latencia deben usar `decision_time`.
- El CSV de replay añade la columna `decision_time` (177 columnas en total).

### 2.3 Contexto superior con datos futuros

**Antes**

- `tools/feature_replay.py` cortaba con `h1[h1.index <= corte]`, `h4[...]`, `d1[...]`. El índice resampleado es el **inicio** del bucket, así que se incluía el bucket en formación con su OHLC completo, calculado con M15 posteriores al corte.
- `kernel/backtest.py` y `kernel/binary/engine.py` hacían lo mismo vía `searchsorted` sobre el frame resampleado completo.
- Cuantificación: el 100 % de las señales del replay tenía alguna vela superior con futuro. El futuro medio era 45 min en H1, 225 min en H4 y 1.424 min en D1.
- El runtime live sí era causal: reconstruía H1/H4/D1 desde el buffer de M15 cerradas.

**Después**

- `kernel/contexto_superior.py` implementa `ContextoSuperiorCausal`.
- Para cada corte entrega:
  - velas superiores **cerradas** (estrictamente anteriores al bucket actual);
  - el bucket actual **en formación**, agregado solo con M15 cuyo cierre es `<= decision_time`;
  - nunca una M15 posterior al instante de decisión.
- `tools/feature_replay.py`, `kernel/backtest.py` y `kernel/binary/engine.py` usan ese contexto.
- Las EMAs H4/D1 se recalculan sobre el frame causal, no sobre el frame completo.
- Verificación: el frame causal coincide exactamente con el resample del buffer live en 7 cortes de prueba.

**Impacto medido**

- El signo de `ctx_h4_ema20_vs_50_atr` coincide con el baseline anterior en 97,8 % de las señales.
- El signo de `ctx_d1_ema50_vs_200_atr` coincide en 99,2–99,4 %.
- No todas las features cambian, pero las que dependen del máximo/mínimo/cierre del bucket en formación sí. Por eso el re-baseline es obligatorio.

---

## 3. Antes / después

### 3.1 Señales del replay

| Métrica | Antes | Después |
|---|---:|---:|
| Señales EURUSD | 8.959 | **8.957** |
| Señales XAUUSD | 8.932 | **8.933** |
| Columnas | 176 | **177** |
| IDs comunes EURUSD | — | 8.956 / 8.957 |
| IDs comunes XAUUSD | — | 8.930 / 8.933 |
| Rango EURUSD (`entry_time`) | 2026-05-12 16:00 → 2026-11-06 18:00 | 2026-05-12 16:45 → 2026-11-06 18:15 |
| Rango XAUUSD (`entry_time`) | 2026-05-12 20:00 → 2026-11-06 17:30 | 2026-05-12 20:30 → 2026-11-06 18:30 |

La dirección y el detector de las señales comunes **no cambian**. Las diferencias son señales de borde que aparecen o desaparecen al corregir el contexto.

### 3.2 Holdout h3 (base, todas las señales)

| Activo | Antes | Después |
|---|---|---|
| EURUSD | n=1.959, WR 48,7 %, EV −9,42 %, boot [−15,36, −3,49] | n=1.960, WR 48,7 %, EV **−9,47 %**, boot [−15,41, −3,54] |
| XAUUSD | n=1.908, WR 47,8 %, EV −13,01 %, boot [−16,97, −8,57] | n=1.911, WR 47,8 %, EV **−13,05 %**, boot [−17,01, −8,59] |

Las 32 combinaciones a priori siguen siendo negativas en ambos activos. No había supervivientes que confirmar.

### 3.3 Escaneo de señales PIVOT

| Estudio | Antes | Después |
|---|---|---|
| EURUSD descubrimiento | 456 tests, 220 primarios, 0 supervivientes; mejor p 0,1385 (`h4_pullback` h4) | 456 tests, 220 primarios, **0**; mejor p **0,2803** (`det_d5` h4) |
| XAUUSD descubrimiento | 448 tests, 220 primarios, 0; mejor p 0,6665 (`tipo_a` h4) | 448 tests, 220 primarios, **0**; mejor p **0,7020** (`tipo_a` h4) |
| XAUUSD ventana completa | 456 tests, 228 primarios, 0 | 456 tests, **220 primarios**, **0**; mejor p **0,8960** (`tipo_a` h4) |

Cambios concretos relevantes:

- `h4_pullback` h4 EURUSD en descubrimiento: antes n=426, WR 56,1 %, EV +4,91 %, p=0,1385; después n=428, WR 53,5 %, EV +0,05 %, p=0,4952. **El “mejor” resultado de descubrimiento desaparece.**
- `h4_pullback` h4 EURUSD en ventana completa: antes EV −2,63 %; después **−7,19 %**.
- `det_d5` h4 EURUSD no cambia: n=255, WR 55,3 %, EV +3,40 %, p=0,2803 en descubrimiento; n=324, WR 58,0 %, EV +8,51 %, p=0,0503 en ventana completa. Sigue siendo un artefacto dependiente de octubre, no un hallazgo.

### 3.4 Ablación (WR %, h1–h4)

| Variante | EURUSD antes | EURUSD después | XAUUSD antes | XAUUSD después |
|---|---|---|---|---|
| H4_only | 49,3 / 49,5 / 49,9 / 50,4 | 49,3 / 49,9 / 49,9 / 49,8 | 50,4 / 50,8 / 50,7 / 50,7 | 51,0 / 51,2 / 51,0 / 51,0 |
| H1_only | 49,0 / 49,1 / 49,7 / 49,7 | 49,2 / 49,5 / 50,0 / 49,8 | 49,8 / 49,8 / 49,6 / 49,6 | 50,5 / 50,4 / 50,1 / 50,2 |
| H4+H1 | 49,1 / 49,4 / 49,9 / 50,3 | 49,3 / 49,9 / 50,2 / 49,9 | 50,2 / 50,4 / 50,2 / 50,2 | 51,1 / 51,1 / 50,8 / 50,8 |
| `siempre_long` | 47,9 / 48,0 / 47,9 / 47,9 | 48,7 / 48,8 / 48,8 / 48,7 | 49,2 / 48,5 / 48,5 / 48,4 | 50,6 / 50,1 / 50,0 / 50,2 |
| PIVOT | 47,6 / 48,5 / 48,1 / 48,7 | 47,6 / 48,5 / 48,1 / 48,7 | 48,2 / 48,6 / 48,5 / 48,7 | 48,2 / 48,6 / 48,5 / 48,7 |
| PIVOT+H4+H1 | 48,3 / 49,1 / 48,6 / 49,6 | 47,8 / 48,5 / 47,8 / 48,8 | 48,9 / 50,0 / 48,7 / 48,2 | 48,5 / 49,4 / 48,1 / 47,7 |

Conclusión: el contexto superior no aporta dirección. PIVOT queda **igual o por debajo** de `siempre_long` (hasta 2,4 pp por debajo en XAUUSD h1). Todos los EV siguen negativos (−6,2 % a −12,8 %).

### 3.5 Escaneo a nivel de vela

| Activo | Antes (publicado) | Después | Supervivientes |
|---|---:|---:|---:|
| EURUSD | 464 tests | 464 tests | **0** |
| XAUUSD | 454 tests | **462 tests** | **0** |

**Advertencia metodológica importante:** el baseline anterior de `bar_edge` se generó con ~6 meses de M15 (n≈428 por hora), no con los 12 meses completos. El nuevo usa 12 meses (n≈928 por hora). Por eso las cifras de `n`, WR y p **no son comparables directamente**.

Para aislar el efecto, se ejecutó el código anterior con los 12 meses completos: los 464/462 tests coinciden **exactamente** con los nuevos en `n`, `wins`, `wr`, `ev`, `p`, `q` y `criterio`. Es decir, `bar_edge` no usa el contexto superior y la corrección no lo afecta; el único cambio es la ventana.

Mejores resultados nominales nuevos:

- EURUSD: `rsi_lt30_L` h3, n=879, WR 55,9 %, EV +3,90 %, p=0,1064, q=1,0.
- XAUUSD: `hora_21_S` h2, n=124, WR 58,1 %, EV +5,68 %, p=0,2425, q=1,0.

Ninguno sobrevive FDR. Las conclusiones anteriores sobre horas concretas (`hora_20_L`, `hora_09_L`, etc.) correspondían a la muestra de 6 meses y **no deben citarse como resultados de 12 meses**.

### 3.6 Patrones intradía

| Activo | Antes | Después | Supervivientes |
|---|---:|---:|---:|
| EURUSD | 168 tests | 168 tests | **0** |
| XAUUSD | 184 tests | 184 tests | **0** |

Los valores de `n`, `wins`, `wr`, `ev`, `p`, `q` y `criterio` son idénticos al baseline. `pattern_edge.py` no usa el contexto superior; la corrección no lo toca.

---

## 4. Verificación ejecutada

| Verificación | Resultado |
|---|---|
| `python -m compileall -q core kernel estrategias scripts tools tests` | OK |
| `python -m pytest -q tests/unit` | **120/120 passed** |
| Contexto causal vs resample live en 7 cortes | coincidencia exacta |
| Smoke replay 1.200 velas, antes vs después | mismos IDs, dirección, detector, `entry_price` y etiquetas; cambian solo features de contexto/sesión |
| `bar_edge` código anterior con 12 meses vs nuevo | idéntico en 464/462 tests |
| `pattern_edge` antes vs después | idéntico en 168/184 tests |
| Escaneos, ablación, holdout y resumen | re-ejecutados; 0 supervivientes |

Tests nuevos:

- `tests/unit/test_contexto_superior.py` (6 tests): envenena velas futuras y verifica que el frame no las usa; comprueba que la última vela es el agregado manual; demuestra que el bug original habría fallado; verifica que la base D1 solo aporta días cerrados.
- `tests/unit/test_referencias_temporales.py` (4 tests): `decision_time` es el cierre; la alerta muestra cierre UTC y sesión coherente; el parser de metadatos lee hora/sesión; la deriva de precio se muestra cuando existe.

---

## 5. Archivos modificados

| Archivo | Cambio |
|---|---|
| `kernel/contexto_superior.py` | **Nuevo.** Contexto H1/H4/D1 causal compartido. |
| `core/estructuras.py` | Propiedad `Signal.decision_time`. |
| `core/alertas.py` | Hora de cierre UTC, sesión coherente, precio al enviar. |
| `core/motor_v8.py` | Sesión/kill zone calculadas en `decision_time`. |
| `kernel/deriv_runtime.py` | `decision_ts` en la serialización; precio actual en la alerta. |
| `tools/feature_replay.py` | Contexto causal, `decision_time`, `ctx_hour` en cierre. |
| `kernel/backtest.py` | Contexto causal y EMAs H4/D1 recalculadas. |
| `kernel/binary/engine.py` | Contexto causal y EMAs H4/D1 recalculadas. |
| `tests/unit/test_contexto_superior.py` | **Nuevo.** Regresión de look-ahead. |
| `tests/unit/test_referencias_temporales.py` | **Nuevo.** Regresión de referencias. |

---

## 6. Qué NO cambia

- El veredicto: **no hay edge confirmado**.
- La decisión: **shadow, sin dinero real, sin promoción**.
- La producción: no se reinició ni se modificó.
- Los escaneos OTC y el walk-forward mensual.
- `pattern_edge` y `bar_edge` con la misma ventana.
- La definición de etiquetas: `entry = close[t]`, `ret_h = close[t+h] − entry`, horizonte por posición.
- La familia de tests y el FDR: no se añadieron ni quitaron condiciones para “mejorar” el resultado.

---

## 7. Reproducción

```bash
# 1. Compilar y tests
python -m compileall -q core kernel estrategias scripts tools tests
python -m pytest -q tests/unit

# 2. Replay con la ventana exacta
python tools/make_replay_window.py --symbol EURUSD --out-dir /tmp/pivot-repro/data
python tools/make_replay_window.py --symbol XAUUSD --out-dir /tmp/pivot-repro/data
python tools/feature_replay.py --symbol EURUSD \
  --m15 /tmp/pivot-repro/data/eurusd_M15.csv --d1 data/eurusd_D1.csv \
  --warmup 500 --out-dir /tmp/pivot-repro/results
python tools/feature_replay.py --symbol XAUUSD \
  --m15 /tmp/pivot-repro/data/xauusd_M15.csv --d1 data/xauusd_D1.csv \
  --warmup 500 --out-dir /tmp/pivot-repro/results

# 3. Pipeline
OUT=/tmp/pivot-repro/results bash tools/run_full_analysis.sh
```

Salidas esperadas: **8.957** señales EURUSD y **8.933** XAUUSD, **177 columnas**, 0 supervivientes, holdout h3 EURUSD −9,47 % y XAUUSD −13,05 %.

---

## 8. Lectura para el auditor

La corrección **no convierte el sistema en rentable ni en no rentable**. Elimina una fuente de look-ahead que afectaba al contexto superior y hace que el replay use la misma convención causal que el runtime live. El baseline corregido sigue siendo negativo y estadísticamente indistinguible del drift.

Si un auditor encuentra una cuarta referencia desfasada, debe reportarla con archivo, línea y comando reproducible. No se debe “arreglar” reejecutando escaneos con familias distintas ni reutilizando el holdout para seleccionar.
