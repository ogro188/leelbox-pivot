# Limitaciones

**Corte:** 2026-11-07 UTC. Este documento enumera lo que el repositorio **no** permite concluir y los sesgos conocidos. Es parte del material de auditoría, no una lista de excusas.

---

## 1. Datos

1. **12 meses es el máximo disponible.** La API de Deriv devolvió 12 meses para M15; no hay 24. Cualquier afirmación sobre estabilidad de largo plazo es limitada.
2. **Los CSV H1/H4 incluidos no cubren 12 meses.** Son las últimas páginas (440/425 y 214 velas). El replay deriva H1/H4 desde M15; los CSV H1/H4 son solo una muestra de contraste.
3. **Volumen de forex = 0.** Deriv devuelve `volume=0` en `frxEURUSD`/`frxXAUUSD`. Las features que dependen de volumen (`sweep_volume_ratio`, `filtro_volumen_ratio`, `volume_ratio`) no son informativas en estos CSV.
4. **Precios públicos, no de un broker concreto.** El payout y la ejecución reales pueden diferir de los de Deriv/IQ Option.
5. **OTC tiene ~6 días de historia** (581 velas M15 por activo) y warmup insuficiente para H1/H4; la muestra efectiva es ~4 días. No hay base para conclusiones de meses.
6. **La historia OTC no se distribuye.** El auditor solo puede revisar los agregados de `results/otc_validation.csv` y `results/otc_features.csv`; no puede recalcular el payout real desde las DB originales.

---

## 2. Replay y fidelidad

1. **El replay cubre ~82,5 % (EURUSD) y ~80,6 % (XAUUSD) de las señales de producción.** Emite además señales extra. El porcentaje se midió sobre el replay anterior; el replay corregido cambia 2–3 señales de borde por activo. Las conclusiones se apoyan en el replay **y** en los resultados reales de producción, pero el sesgo de selección del replay no es cero.
2. **h4 no está validado contra producción.** Solo hay 3 filas EURUSD y 6 XAUUSD con `h4` medido en producción; las conclusiones de h4 son replay-only.
3. **El replay publicado usó 6 meses, no 12.** Los CSV de señales cubren 2026-05-12 → 2026-11-06. El M15 de 12 meses incluido es un superconjunto; para reproducir exactamente hay que usar el subconjunto descrito en `docs/REPRODUCIBILITY.md`.
4. **El replay usa `fast_engine.py`.** Se validó contra el motor sin acelerar, pero una diferencia sutil de implementación podría afectar los conteos. El auditor debe revisar esa equivalencia.
5. **D1 EMA200 no existe antes de ~septiembre 2026.** `trend_d1` es `NEUTRO` en los primeros meses; los filtros D1 no son utilizables en toda la muestra.
6. **El motor no se ejecutó con la misma versión de pandas/numpy en todos los entornos.** Diferencias de redondeo o de resample pueden cambiar algunas señales de borde.
7. **El contexto superior ya es causal, pero la auditoría externa debe verificarlo.** `kernel/contexto_superior.py` agrega el bucket H1/H4/D1 en formación solo con M15 cerradas hasta `decision_time`; los tests envenenan velas futuras. Aun así, es el punto más delicado del replay.

---

## 3. Etiquetas y ejecución

1. **La entrada de referencia es el close de la vela de señal, no el open siguiente.** `feature_replay.py` usa `entry_price = close[t]`. `entry_time` es la apertura de esa vela y `decision_time` su cierre. Es un supuesto **optimista**: en la práctica se entraría en el open de `t+1` o después; el open suele coincidir con el close, pero puede saltar. No se modela gap ni slippage.
2. **El horizonte se cuenta por posición (`pos+h`), no por diferencia de timestamps.** Si faltara una vela, el horizonte se desplazaría. Los M15 incluidos no tienen duplicados ni nulos, pero los fines de semana no existen.
3. **`mfe_h*`/`mae_h*` incluyen la vela de señal.** Pueden capturar excursiones anteriores a la entrada; no se usan para win/loss.
4. **`pattern_edge.py` no usa el mismo esquema de entrada.** Ese escaneo entra en `open[t+1]` y sale en `close[t+h]`, con chequeo de continuidad por `epoch`. Sus resultados no son directamente comparables con las etiquetas de `feature_replay.py`, que usan `close[t]` y cuentan el horizonte por posición.
4. **Resolución binaria al close de `t+h`.** No se modelan ticks intravela, empates, expiración anticipada, spread, comisión ni slippage. Un empate cuenta como pérdida (`win = 0`).
5. **El payout es fijo por horizonte/activo.** No se modela la variación intraday del payout ni la disponibilidad de contratos.
6. **El modelo asume que se puede entrar exactamente al precio de referencia.** En opciones binarias reales, el precio de entrada y la hora de expiración los fija el broker; la diferencia puede ser material.

---

## 4. Estadística

1. **Multiplicidad.** Se aplicó BH-FDR al 10 % dentro de cada activo/estudio. Los escaneos de velas, patrones y OTC son familias distintas; no se corrigieron entre sí. Un q-valor de 1,0 no significa que el p-valor sea 1.
2. **h5–h8 son exploratorias.** No entran en el FDR y no deben usarse para promover nada.
3. **El bootstrap remuestrea días.** Con ~100–250 días, el intervalo es grueso y puede subestimar la dependencia entre días consecutivos.
4. **Muestras pequeñas.** Varios candidatos tienen n < 150 (NYOR13 n=118, LOR4 n=71, OTC n=133). Un p-valor nominal bajo en estas muestras es frágil.
5. **Selección post-hoc.** Los escaneos exploratorios (velas, patrones, OTC) se miraron después del escaneo principal. Aunque cada familia tenga su propio FDR, la decisión de qué mirar está influida por los resultados. El brief pide auditar este punto.
6. **El holdout no es infinito.** Se usó para confirmar el baseline y las hipótesis a priori; no para tuning. Aun así, el mismo período se usó en varios resúmenes, y eso reduce su valor como test limpio.
7. **Los resultados de producción no son un OOS limpio.** Provienen del mismo sistema y del mismo período; además, la DB de producción no se distribuye. Son un contraste independiente del replay, no una validación externa.
8. **No se optimizaron TP/SL.** El análisis de salidas es posterior y separado; no se usó para seleccionar. Si alguien optimiza TP/SL sobre estos datos, el resultado no es comparable.

---

## 5. Sistema y operación

1. **PIVOT no ejecuta órdenes.** Genera señales y las registra. La capa de alertas está desactivada por defecto (`PIVOT_ALERTAS_LIVE=0`).
2. **El `DATABASE_URL` de producción apuntaba a `/tmp`.** Es un riesgo operativo (base efímera), no un resultado de investigación. No se tocó.
3. **Un solo host.** No hay alta disponibilidad, ni backups verificados en este repo, ni migración a eMMC completada.
4. **El frontend y los servicios systemd no se incluyen.** La API es opcional para la revisión.
5. **El colector OTC es solo lectura.** No se conecta a la cuenta ni ejecuta operaciones.
6. **La migración USB → eMMC está pendiente.** No se tocó durante este trabajo.

---

## 6. Código y columnas

1. **Columnas no pobladas.** `cr`, `bs_pips`, `range_break_pips`, `fvg_size_pips`, `spread_pips`, `volume_ratio` y `g3_eficiencia` son constantes 0. `entry_bar_shift` es 0 en el CSV. Ver `docs/DATA_DICTIONARY.md`.
2. **Campos específicos de detector.** `fvg_*` solo aplica a D3/D3_DEF; `ob_*` a D4; `mss_*` a D5. Los ceros en el resto son estructurales, no datos faltantes.
3. **`measured`, `retorno`, `mfe`, `mae` y las versiones `_cerrado`** son listas de producción serializadas; en el replay están a `False`/0. No sirven para evaluar el replay.
4. **`validate_labels.py` y `replay_report.py` requieren `pivotradar_data/`.** Sin esa carpeta fallan; es esperado.
5. **`fetch_history.py` puede truncar H1/H4.** La paginación de la API no garantiza la historia completa de esos timeframes.
6. **No hay tests de integración con datos reales en el repo.** Los tests unitarios cubren detectores, contratos, persistencia y API; los de integración pueden requerir DB/API.

---

## 7. Qué se puede y qué no se puede concluir

**Se puede concluir:**

- En esta muestra, PIVOT no supera el break-even de las opciones binarias a los payouts usados.
- El contexto H4/H1 no mejora la dirección; PIVOT está al nivel de `siempre_long`.
- Los escaneos de velas y patrones no producen supervivientes FDR.
- El candidato OTC EURUSD / D2_ANTICIPACION no se sostiene; el de XAUUSD / h1 alineado es solo una hipótesis.

**No se puede concluir:**

- Que PIVOT sea rentable en otro régimen, otro broker u otro payout.
- Que ninguna hipótesis de las exploradas pueda funcionar con más datos o mejor ejecución.
- Que el veredicto negativo sea inmune a un error de implementación; para eso está la auditoría.
- Que el sistema pueda operarse con dinero real. **No debe hacerse.**

---

## 8. Sesgos que el auditor debe buscar

1. Look-ahead en el resample H1/H4/D1, en `kernel/contexto_superior.py` o en los detectores.
2. Uso del close de la vela de señal como entrada y del high/low de esa vela en MFE/MAE; coherencia entre `entry_time` (apertura) y `decision_time` (cierre).
3. Fuga entre descubrimiento y holdout, o selección de condiciones después de ver el holdout.
4. Familia de tests mal definida o FDR aplicado solo a un subconjunto.
5. Bootstrap que trata señales del mismo día como independientes.
6. Diferencia entre el replay y la producción que favorezca al replay.
7. Columnas no pobladas usadas como si fueran señales.
8. Conclusiones que mezclan estudios con cortes temporales distintos.

Si encuentras alguno de estos problemas, el veredicto negativo puede cambiar en una dirección **u otra**. Repórtalo con archivo y línea.
