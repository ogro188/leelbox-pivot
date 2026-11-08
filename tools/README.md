# Herramientas de análisis

Scripts reproducibles para generar señales, escanear hipótesis y validar resultados. **No forman parte del runtime de producción** y no ejecutan órdenes.

## Requisitos

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r ../requirements.txt
```

Ejecutar siempre desde la raíz del repositorio:

```bash
cd ..
python tools/<script>.py --help
```

## Orden del pipeline

| Paso | Script | Entrada | Salida |
|---:|---|---|---|
| 1 | `fetch_history.py` | API Deriv | `data/{symbol}_{TF}.csv` |
| 2 | `feature_replay.py` | `data/*_M15.csv` + `data/*_D1.csv` | `results/{symbol}_signals.csv`, `*_meta.json` |
| 3 | `edge_scan.py` | `results/*_signals.csv` | `results/edge_scan_*.csv`, `scan_*.txt` |
| 4 | `ablation.py` | `data/` + señales | `results/ablation_*.csv` |
| 5 | `holdout.py` | señales + scan de descubrimiento | `results/holdout_*.csv` |
| 6 | `walkforward.py` | señales | `results/walkforward_*.csv` |
| 7 | `bar_edge.py` | `data/*_M15.csv` | `results/bar_edge_*.csv` |
| 8 | `pattern_edge.py` | `data/*_M15.csv` | `results/pattern_edge_*.csv` |
| 9 | `otc_validate.py` | DB OTC + `otc_features.csv` | `results/otc_validation.csv` |
| 10 | `summarize.py` | resultados | `results/summary.txt` |

`run_full_analysis.sh` encadena los pasos 2–6 y 10. Los pasos 1, 7, 8 y 9 se ejecutan aparte porque requieren red o bases OTC. Acepta `PYTHON`, `OUT` y `BOOTSTRAP` como variables de entorno; por defecto usa `python3`, `results` y 2.000 remuestreos. Si no existe `pivotradar_data/`, omite los pasos de fidelidad contra producción.

## Descripción de scripts

### Datos y replay

- **`fetch_history.py`** — descarga velas M15/H1/H4/D1 desde Deriv. Solo lectura. La API limita M15 a 12 meses.
- **`feature_replay.py`** — recorre las velas con el motor real en proceso, captura 176 columnas por señal y calcula etiquetas h1–h8. Es el paso más lento (~26 min por activo en el host original).
- **`fast_engine.py`** — aceleradores del motor usados por el replay. No cambia la lógica; se valida contra el motor sin acelerar.
- **`replay_harness.py` / `replay_fast_test.py` / `replay_profile.py`** — utilidades de desarrollo para comparar y perfilar el replay.
- **`replay_report.py`** — compara el replay con la base de producción. Requiere `pivotradar_data/`; no está incluido.
- **`validate_labels.py`** — compara `ret_h1..h4` contra `senales_resultados`. Requiere la DB de producción.

### Escaneos

- **`edge_scan.py`** — tests univariados sobre señales PIVOT: alineación H4/H1, pullback, volatilidad, confluencia, sesión, detector. BH-FDR al 10 %, Wilson, bootstrap por día, payout por horizonte.
- **`bar_edge.py`** — tests a nivel de vela: calendario, momentum/reversión, RSI14, ATR, EMA50, cuerpo/rango. No depende de PIVOT.
- **`pattern_edge.py`** — patrones intradía: ARB, LOR3/LOR4, NYOR12/NYOR13, SWEEP, CLOSE, PDH; dirección base y fade.
- **`holdout.py`** — evalúa en holdout los supervivientes y las hipótesis a priori, con umbrales congelados.
- **`ablation.py`** — compara H4-only, H1-only, H4+H1, PIVOT, PIVOT+H4+H1 y `siempre_long`.
- **`walkforward.py`** — estabilidad mensual de las condiciones.
- **`exit_analysis.py`** — análisis posterior de salidas (TP/SL); no se usa para seleccionar.
- **`payout_ev.py`** — calcula EV con payout real por señal.
- **`summarize.py`** — genera el resumen de texto.
- **`query_bar_edge.py` / `inspect_scan.py` / `detector_counts.py`** — utilidades de consulta y conteo.

### OTC

- **`otc_context.py`** — extrae features de contexto de las señales OTC.
- **`otc_validate.py`** — valida con payout real por señal y bootstrap por día.
- **`otc_forward_report.py`** — reporte de forward test en shadow.

## Convenciones

- Fechas en UTC, formato ISO (`YYYY-MM-DD`).
- `ret_h*` está en **puntos** del activo, no en porcentaje.
- `ev` y `winrate` están en **porcentaje**.
- El bootstrap remuestrea **días**, no señales.
- Los scripts de escaneo usan `--out-dir results` por defecto.
- `feature_replay.py`, `replay_report.py` y `validate_labels.py` buscan la DB en `./pivotradar_data/`; esa carpeta no se distribuye.

## Advertencias

- Los scripts de replay **no tocan producción**: usan una DB nula y desactivan alertas.
- `fetch_history.py` requiere red y credenciales solo si se consultan datos privados.
- `replay_report.py` y `validate_labels.py` fallan si no existe `pivotradar_data/`; es esperado en esta extracción.
- No promover ningún resultado sin el protocolo de `docs/VALIDATION_PROTOCOL.md`.
