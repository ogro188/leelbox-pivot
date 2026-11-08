# Reproducibilidad

**Objetivo:** que un revisor independiente pueda recalcular las tablas y verificar los números sin acceso a producción.

---

## 1. Entorno

- Python 3.11 o 3.12.
- Dependencias: `requirements.txt` (pandas, numpy, fastapi, uvicorn, websockets, requests, pytest, httpx, ta, python-dotenv).
- No se necesita cuenta de Deriv para trabajar con los CSV incluidos.
- No se necesita IQ Option para auditar los resultados OTC; las DB originales no se distribuyen.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

El replay original se ejecutó en un host ARM con Python 3.11, pandas 2.2.3 y numpy 2.2.4. La copia sanitizada se validó con Python 3.12, pandas 3.0.6 y numpy 2.5.3 para compilación, tests y escaneos ligeros. Si aparece una diferencia numérica, revisar primero la versión de pandas/numpy.

---

## 2. Verificación rápida (sin replay)

```bash
cd pivot-trading-system

# 1. Compilación
python -m compileall -q core kernel estrategias scripts tools tests

# 2. Tests unitarios (los de integración pueden requerir API/DB)
python -m pytest -q tests/unit

# 3. Escaneo de señales ya calculadas (rápido)
python tools/edge_scan.py \
  --inputs results/eurusd_signals.csv \
  --payouts-by-h 0.85,0.86,0.86,0.87,0.87,0.87,0.87,0.87 \
  --hasta 2026-09-30 --tag disc --out-dir /tmp/pivot-repro

# 4. Holdout
python tools/holdout.py \
  --signals results/eurusd_signals.csv \
  --scan /tmp/pivot-repro/edge_scan_eurusd_disc.csv \
  --split 2026-10-01 --desc-hasta 2026-09-30 \
  --payouts-by-h 0.85,0.86,0.86,0.87,0.87,0.87,0.87,0.87 \
  --out-dir /tmp/pivot-repro

# 5. Escaneo a nivel de vela y patrones (minutos)
python tools/bar_edge.py --symbol EURUSD --bootstrap 300 --out-dir /tmp/pivot-repro
python tools/pattern_edge.py --symbol EURUSD --bootstrap 300 --out-dir /tmp/pivot-repro
```

Los resultados deben coincidir con `results/` en las columnas `n`, `wins`, `wr`, `p`, `q` y `criterio` (puede haber diferencias mínimas por versión de numpy/pandas y por el bootstrap aleatorio si no se fija semilla).

---

## 3. Replay completo

### 3.1 Ventana original

Los CSV de señales se generaron con un subconjunto de **6 meses**:

| Activo | Velas M15 | Inicio | Fin | Señales |
|---|---:|---|---|---:|
| EURUSD | 12.506 | 2026-05-05 08:30 UTC | 2026-11-06 20:45 UTC | 8.959 |
| XAUUSD | 12.014 | 2026-05-05 08:30 UTC | 2026-11-06 20:45 UTC | 8.932 |

Ese subconjunto son las **últimas N filas** del M15 de 12 meses incluido. El `m15_total` de `results/*_meta.json` lo confirma. El warmup es de 500 velas; por eso la primera señal aparece el 2026-05-12.

### 3.2 Reconstruir el subconjunto

```bash
python tools/make_replay_window.py --symbol EURUSD --out-dir /tmp/pivot-repro/data
python tools/make_replay_window.py --symbol XAUUSD --out-dir /tmp/pivot-repro/data
```

El script copia las últimas 12.506 / 12.014 filas del M15 y deja `eurusd_M15.csv` / `xauusd_M15.csv` listos para el replay.

### 3.3 Ejecutar el replay

```bash
python tools/feature_replay.py \
  --symbol EURUSD \
  --m15 /tmp/pivot-repro/data/eurusd_M15.csv \
  --d1 data/eurusd_D1.csv \
  --warmup 500 \
  --out-dir /tmp/pivot-repro/results

python tools/feature_replay.py \
  --symbol XAUUSD \
  --m15 /tmp/pivot-repro/data/xauusd_M15.csv \
  --d1 data/xauusd_D1.csv \
  --warmup 500 \
  --out-dir /tmp/pivot-repro/results
```

Tiempo de referencia en el host original: **1.576,8 s** EURUSD y **1.549,6 s** XAUUSD (~26 min por activo). En un x86 moderno suele ser más rápido.

Salidas esperadas:

- `eurusd_signals.csv` / `xauusd_signals.csv` con 8.959 / 8.932 filas y 176 columnas.
- `*_meta.json` con rango, velas, segundos y validación de etiquetas.
- La validación de etiquetas contra producción devuelve `db no existe` si no se aporta `pivotradar_data/`; es esperado.

### 3.4 Pipeline completo

```bash
bash tools/run_full_analysis.sh
```

El script detecta si existe `pivotradar_data/`; si no existe, omite los pasos que requieren la DB de producción y avisa. Los escaneos, la ablación y el holdout se ejecutan igual.

---

## 4. Checksums

SHA-256 de los archivos clave (corte 2026-11-07):

| Archivo | SHA-256 |
|---|---|
| `data/eurusd_M15.csv` | `7f1c862cda5c0c12557979cfe606864e75a389f0dd0e572925fe3c2980f92349` |
| `data/xauusd_M15.csv` | `12d93f645b2cdbedcde8b2e1a1e3cb17c0a676ba370ceab626b6b5a6e6220543` |
| `data/eurusd_D1.csv` | `f955ac6b03b374dba00cc51e772bde72a38c353fcd8dbe4ba78fd18dad4695c4` |
| `data/xauusd_D1.csv` | `43b8e6d43f4c5d57e3733815e0eb60e5405842f93d64d4e437b39e30eaaf8e43` |
| `results/eurusd_signals.csv` | `e6e0e925dc835933118df53f6d3696c631552c61fdea2fd83c674e773ec62adc` |
| `results/xauusd_signals.csv` | `ce09399761d0d35ba5d14428c4d57526ad00cad091b74859ed9177ccfc64a9cf` |
| `results/edge_scan_eurusd_disc.csv` | `c4971c39fea7cc56afd8e15467b5a934c05add173df02e8396bd30549828ac30` |
| `results/edge_scan_xauusd_disc.csv` | `77aefd454fbc6a1b02f66c0634dad0bf6331fb0fa56c6a89d7e41c2a9e2ec0c6` |
| `results/bar_edge_eurusd.csv` | `ebe15df523a47d8a30add5f46a6762a6c378e0d6a94a3712cb2be796d5f8c0e6` |
| `results/pattern_edge_eurusd.csv` | `dac9b7f73517728372347de7911b925cad6a2549b580d76fb07494a26086d76e` |
| `results/otc_validation.csv` | `f024df32d099862cca3d52c95ff47fd2492cd2d66a8c08a31b3c7c6d602ea7c9` |

Verificar:

```bash
sha256sum -c <<'EOF'
7f1c862cda5c0c12557979cfe606864e75a389f0dd0e572925fe3c2980f92349  data/eurusd_M15.csv
12d93f645b2cdbedcde8b2e1a1e3cb17c0a676ba370ceab626b6b5a6e6220543  data/xauusd_M15.csv
e6e0e925dc835933118df53f6d3696c631552c61fdea2fd83c674e773ec62adc  results/eurusd_signals.csv
ce09399761d0d35ba5d14428c4d57526ad00cad091b74859ed9177ccfc64a9cf  results/xauusd_signals.csv
EOF
```

---

## 5. Qué se puede reproducir sin producción

| Elemento | ¿Reproducible? | Nota |
|---|---|---|
| Señales M15 (8.959/8.932) | Sí, con el subconjunto exacto | ~26 min por activo. |
| Escaneos PIVOT | Sí | Desde los CSV de señales. |
| Holdout y ablación | Sí | Desde los CSV. |
| Escaneos de velas/patrones | Sí | Desde M15 de 12 meses. |
| Resultados OTC | Parcial | Faltan las DB originales; solo se pueden auditar los CSV agregados. |
| Producción real (`senales_resultados`) | No | La DB no se distribuye. Se incluyen los agregados en `docs/EDGE_FINDINGS.md`. |
| Fidelidad replay vs producción | No | Requiere `pivotradar_data/` y los IDs de producción. |

---

## 6. Advertencias

- No ejecutar `feature_replay.py` contra una instalación de producción ni contra su base de datos: el script usa una DB nula, pero el objetivo es trabajar sobre la copia.
- `fetch_history.py` requiere red y puede cambiar si Deriv modifica la API o los límites.
- El bootstrap usa un RNG sin semilla fija en algunas corridas; los intervalos pueden variar en el último decimal. Los p-valores y q-valores no.
- Si se cambia el orden de las condiciones o se añaden tests, hay que **redefinir la familia y recalcular FDR**.
- Cualquier resultado nuevo debe seguir `docs/VALIDATION_PROTOCOL.md`.
