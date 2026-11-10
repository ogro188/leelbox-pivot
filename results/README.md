# Resultados

Salidas de los análisis. **Ningún archivo de esta carpeta constituye una recomendación de operación.** El veredicto vigente es negativo: no hay edge confirmado.

## Archivos principales

| Archivo | Contenido |
|---|---|
| `EDGE_FINDINGS.md` / `OTC_FINDINGS.md` | Informes de veredicto. La copia canónica está en `docs/`. |
| `summary.txt` | Resumen de escaneos, ablación, holdout y OTC. |
| `eurusd_signals.csv` / `xauusd_signals.csv` | 8.957 / 8.933 señales con 177 columnas de features y etiquetas. |
| `eurusd_meta.json` / `xauusd_meta.json` | Rango, número de velas, configuración y validación de etiquetas. |
| `edge_scan_*_disc.csv` / `*_full.csv` | Tests de señales PIVOT en descubrimiento y ventana completa. |
| `edge_scan_all_disc.csv` / `*_full.csv` | **Solo XAUUSD** (artefacto de la última corrida por activo). Los archivos canónicos son los `edge_scan_<activo>_*`. |
| `scan_*_disc.txt` / `scan_*_full.txt` | Salidas legibles de los escaneos. |
| `ablation_*.csv` / `.txt` | Ablación de capas de contexto. |
| `holdout_*.csv` / `.txt` | Holdout temporal. |
| `walkforward_eurusd.csv` | Estabilidad mensual. |
| `bar_edge_*.csv` | Escaneo a nivel de vela (464 / 462 tests, 12 meses). |
| `pattern_edge_*.csv` | Patrones intradía (168 / 184 tests). |
| `otc_features.csv` | Señales OTC con features y etiquetas. |
| `otc_validation.csv` | Validación OTC con payout real. |
| `labels_*.txt` | Comparación de etiquetas contra producción. |

## Convenciones

- `wr`, `wr_lo`, `wr_hi`, `be`, `payout`, `ev`, `ev_boot_lo`, `ev_boot_hi` están en porcentaje.
- `p` es unilateral contra el break-even; `q` es el valor BH-FDR.
- `criterio = 1` solo si se cumplen **todas** las condiciones del protocolo.
- `n` es el número de señales con etiqueta válida para ese horizonte.
- `dias` es el número de días distintos usados en el bootstrap.
- `ev_payout_m3` / `ev_payout_p3` son sensibilidades con payout −3/+3 pp.

## Advertencias

- Los CSV de señales son grandes (19 MB cada uno) pero contienen solo features y etiquetas, no credenciales.
- Las columnas `cr`, `bs_pips`, `range_break_pips`, `fvg_size_pips`, `spread_pips`, `volume_ratio`, `g3_eficiencia` y `entry_bar_shift` están sin poblar o son constantes en esta exportación. Ver `docs/DATA_DICTIONARY.md`.
- `labels_*.txt` compara contra `senales_resultados` de producción. En esta extracción sanitizada la DB de producción no se distribuye, así que el archivo local muestra `db_ids_con_resultado=0` y `comunes=0`; los porcentajes de coincidencia citados en `docs/EDGE_FINDINGS.md` provienen de la corrida original contra producción.
- Los resultados de señales, escaneos, ablación y holdout se regeneraron el 2026-11-09 con contexto superior causal (`kernel/contexto_superior.py`) y la columna `decision_time`. Antes/después en `docs/REFERENCE_FIX.md`.
- `bar_edge_*.csv` usa 12 meses de M15. El baseline anterior de 454 tests XAUUSD usaba ~6 meses y no es comparable; con la misma ventana, el código anterior y el actual coinciden exactamente.
- No mezclar p-valores de un estudio con q-valores de otro: cada familia tiene su propia corrección.
- Los resultados OTC tienen ~6 días de historia y no son concluyentes.
