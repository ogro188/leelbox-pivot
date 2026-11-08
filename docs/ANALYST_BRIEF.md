# Brief para el analista externo

**Proyecto:** PIVOT — sistema de señales para opciones binarias / forex.
**Objetivo:** auditoría independiente del motor, los datos y el pipeline de validación.
**Estado:** shadow, sin dinero real. No hay edge confirmado.
**Fecha del corte:** 2026-11-07.

---

## 1. Contexto mínimo

PIVOT detecta patrones de estructura de mercado (sweeps de liquidez, FVG, order blocks, MSS) en M15 con contexto H1/H4/D1. La hipótesis original era que la confluencia de estructura, liquidez y contexto daba una ventaja direccional con expiraciones de 15–60 minutos en opciones binarias.

El sistema **no ejecuta órdenes**. Genera señales, las registra y, opcionalmente, las envía por notificación. La producción está en modo shadow con las alertas live desactivadas.

Los análisis realizados hasta ahora concluyen que **no hay edge demostrado**. Este brief no busca que el analista “encuentre” un edge; busca que audite si el veredicto negativo es correcto y si queda alguna hipótesis con mecanismo que merezca una prueba nueva.

---

## 2. Qué revisar

### 2.1 Prioridad alta — integridad de los datos y las etiquetas

1. **Look-ahead / leakage** en:
   - `tools/feature_replay.py` (generación de features y etiquetas),
   - `tools/fast_engine.py` (aceleradores del motor),
   - `core/motor_v8.py` y detectores D0–D5,
   - `tools/bar_edge.py` y `tools/pattern_edge.py`.
2. **Etiquetas**: la implementación usa el **close de la vela de señal** como precio de entrada y el close de `t+h` como salida; el MFE/MAE incluye la vela de señal. ¿Es ejecutable? ¿Introduce sesgo optimista? ¿Debería usarse el open de `t+1`?
3. **Resample H1/H4/D1**: que solo use velas cerradas y que el índice temporal sea correcto.
4. **Replay vs producción**: el replay cubre ~82 % de las señales de producción y emite señales extra. ¿El sesgo de selección invalida las conclusiones? ¿Las diferencias son solo de timing/entrada?

### 2.2 Prioridad alta — estadística

5. **Familia de tests**: ¿está bien definida? ¿El FDR se aplica sobre la familia correcta? ¿h5–h8 deberían entrar?
6. **Bootstrap por día**: ¿respeta la dependencia intra-día? ¿El remuestreo de días es suficiente con ~100–250 días?
7. **Holdout**: ¿los cortes y la purga son suficientes? ¿Hay contaminación por usar el holdout en la ablación o en los resúmenes?
8. **Criterio de supervivencia**: `q ≤ 0,10`, `wr_lo > BE`, `ev_boot_lo > 0`, `n ≥ 100`. ¿Es demasiado laxo o demasiado estricto?
9. **Multiplicidad no declarada**: ¿los escaneos exploratorios (velas, patrones, OTC) se usaron para elegir hipótesis que luego se presentan como pre-registradas?

### 2.3 Prioridad media — modelo binario y ejecutabilidad

10. **Payout/expiry**: ¿el payout por horizonte es correcto? ¿La resolución al close de `t+h` es la que usa el broker? ¿Cómo se tratan empates, ticks y expiraciones intravela?
11. **Spread/slippage**: el escaneo binario no los modela; el backtest spot sí. ¿Cambia el veredicto?
12. **Solapamiento**: las señales pueden solaparse; el bootstrap por día lo mitiga, pero ¿hay autocorrelación residual?

### 2.4 Prioridad media — hipótesis abiertas

13. **EURUSD NYOR13 fade h1**: n=118, WR 58,5 %, EV +8,18 %, p=0,168. ¿Tiene mecanismo o es ruido de selección?
14. **EURUSD `hora_20_L` h4 / `ema_gt_2_S` h4**: nominalmente positivos en descubrimiento y holdout, sin FDR. ¿Sobreviven a una prueba no solapada?
15. **XAUUSD LOR4 fade h8**: n=71, WR 70,4 %, EV +28,9 %, p=0,0037, q=0,697. ¿Es solo muestra pequeña?
16. **XAUUSD-OTC h1 alineado h3**: n=133, WR 60,9 %, EV +13,3 %, IC95 inferior 52,4 % < BE 53,76 %, 5 días. ¿Merece forward test?

### 2.5 Prioridad baja — código y operación

17. Bugs, excepciones silenciosas, supuestos de tipos, divisiones por cero, uso de `iloc`/índices.
18. Problemas de seguridad o datos personales en el repo (debería estar sanitizado).
19. Riesgos operativos: base SQLite efímera, backups, migración pendiente, dependencia de un solo host.

---

## 3. Entregables esperados

1. **Informe escrito** con:
   - veredicto sobre la validez del análisis negativo;
   - lista de bugs/errores metodológicos con archivo y línea;
   - evaluación de cada hipótesis abierta (promover / archivar / forward test);
   - recomendación de próximo experimento, si existe.
2. **Scripts o notebook reproducibles** para cualquier recálculo que hagas.
3. **Tabla de resultados** con los números que hayas verificado y los que no.
4. **Lista de supuestos** que no pudiste verificar con los datos incluidos.

No se espera una estrategia rentable. Se espera una auditoría honesta y específica.

---

## 4. Plan de revisión sugerido (2–4 días)

| Día | Actividad |
|---|---|
| 1 | Leer README, protocolo y arquitectura. Revisar `feature_replay.py` y las etiquetas. Recalcular un subconjunto de señales. |
| 2 | Revisar el escaneo principal, FDR, bootstrap y holdout. Reproducir las tablas de `results/`. |
| 3 | Revisar los escaneos de velas/patrones y las hipótesis abiertas. Buscar leakage y selección post-hoc. |
| 4 | Revisar el modelo binario, la ejecutabilidad y los riesgos operativos. Escribir el informe. |

---

## 5. Acceso y límites

- El repositorio es privado; se comparte con el analista por invitación.
- **No hay acceso a producción ni a bases de datos live.** Los CSV de señales y los resultados son la fuente de verdad para la revisión.
- No se debe operar con dinero real ni promover el sistema a demo durante la revisión.
- Cualquier cambio de código debe hacerse en una rama/forks del repo, no en producción.
- Si se necesita una muestra adicional, se puede solicitar; no se debe asumir acceso al host.

---

## 6. Preguntas de sí/no

- ¿Encontraste look-ahead o leakage? ¿Dónde?
- ¿Las etiquetas son correctas y ejecutables?
- ¿El FDR está bien aplicado?
- ¿El holdout está limpio?
- ¿El replay es suficientemente fiel?
- ¿Alguna hipótesis abierta cumple el criterio de promoción?
- ¿El veredicto negativo se mantiene?
- ¿Hay algún experimento nuevo que valga la pena?

---

## 7. Contacto

Responder con el informe y los scripts en el repositorio o por el canal acordado. Si encuentras un residuo de credenciales o un problema de seguridad, repórtalo de inmediato y no lo publiques.
