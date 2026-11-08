#!/bin/bash
# Análisis completo post-replay. No toca producción.
#
# Uso:
#   bash tools/run_full_analysis.sh
#
# Requiere haber generado antes:
#   results/eurusd_signals.csv y results/xauusd_signals.csv
#   (ver tools/feature_replay.py)
#
# Los pasos de fidelidad contra producción se omiten si no existe
# pivotradar_data/ (esperado en esta extracción sanitizada).
set -euo pipefail

cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD"
OUT="${OUT:-results}"
BOOTSTRAP="${BOOTSTRAP:-2000}"
PY="${PYTHON:-python3}"
EUR_PAY=0.85,0.86,0.86,0.87,0.87,0.87,0.87,0.87
XAU_PAY=0.81,0.82,0.82,0.83,0.83,0.83,0.83,0.83

if ! "$PY" -c 'import pandas, numpy' >/dev/null 2>&1; then
  echo "ERROR: $PY no tiene pandas/numpy. Activa el venv o define PYTHON=/ruta/python." >&2
  exit 1
fi

if [ ! -f "$OUT/eurusd_signals.csv" ] || [ ! -f "$OUT/xauusd_signals.csv" ]; then
  echo "ERROR: faltan $OUT/eurusd_signals.csv o $OUT/xauusd_signals.csv." >&2
  echo "Genera primero las señales con tools/feature_replay.py." >&2
  exit 1
fi

if [ -d pivotradar_data ]; then
  echo "== fidelidad =="
  "$PY" tools/replay_report.py --symbol EURUSD > "$OUT/replay_report_eurusd.txt" 2>&1 || true
  "$PY" tools/replay_report.py --symbol XAUUSD > "$OUT/replay_report_xauusd.txt" 2>&1 || true
  "$PY" tools/validate_labels.py --symbol EURUSD > "$OUT/labels_eurusd.txt" 2>&1 || true
  "$PY" tools/validate_labels.py --symbol XAUUSD > "$OUT/labels_xauusd.txt" 2>&1 || true
else
  echo "== fidelidad: omitida (no existe pivotradar_data/) =="
fi

echo "== scan full (exploratorio) =="
"$PY" tools/edge_scan.py --inputs "$OUT/eurusd_signals.csv" \
  --payouts-by-h "$EUR_PAY" --bootstrap "$BOOTSTRAP" --tag full --out-dir "$OUT" > "$OUT/scan_eurusd_full.txt" 2>&1
"$PY" tools/edge_scan.py --inputs "$OUT/xauusd_signals.csv" \
  --payouts-by-h "$XAU_PAY" --bootstrap "$BOOTSTRAP" --tag full --out-dir "$OUT" > "$OUT/scan_xauusd_full.txt" 2>&1

echo "== scan descubrimiento (mayo-sep) =="
"$PY" tools/edge_scan.py --inputs "$OUT/eurusd_signals.csv" \
  --payouts-by-h "$EUR_PAY" --bootstrap "$BOOTSTRAP" --hasta 2026-09-30 --tag disc --out-dir "$OUT" > "$OUT/scan_eurusd_disc.txt" 2>&1
"$PY" tools/edge_scan.py --inputs "$OUT/xauusd_signals.csv" \
  --payouts-by-h "$XAU_PAY" --bootstrap "$BOOTSTRAP" --hasta 2026-09-30 --tag disc --out-dir "$OUT" > "$OUT/scan_xauusd_disc.txt" 2>&1

echo "== ablation =="
"$PY" tools/ablation.py --symbol EURUSD --signals "$OUT/eurusd_signals.csv" \
  --payouts-by-h "$EUR_PAY" --bootstrap "$BOOTSTRAP" --out-dir "$OUT" > "$OUT/ablation_eurusd.txt" 2>&1
"$PY" tools/ablation.py --symbol XAUUSD --signals "$OUT/xauusd_signals.csv" \
  --payouts-by-h "$XAU_PAY" --bootstrap "$BOOTSTRAP" --out-dir "$OUT" > "$OUT/ablation_xauusd.txt" 2>&1

echo "== holdout (oct-nov) =="
"$PY" tools/holdout.py --signals "$OUT/eurusd_signals.csv" \
  --scan "$OUT/edge_scan_eurusd_disc.csv" --split 2026-10-01 --desc-hasta 2026-09-30 \
  --payouts-by-h "$EUR_PAY" --bootstrap "$BOOTSTRAP" --out-dir "$OUT" > "$OUT/holdout_eurusd.txt" 2>&1
"$PY" tools/holdout.py --signals "$OUT/xauusd_signals.csv" \
  --scan "$OUT/edge_scan_xauusd_disc.csv" --split 2026-10-01 --desc-hasta 2026-09-30 \
  --payouts-by-h "$XAU_PAY" --bootstrap "$BOOTSTRAP" --out-dir "$OUT" > "$OUT/holdout_xauusd.txt" 2>&1

echo "== resumen =="
"$PY" tools/summarize.py --out-dir "$OUT" > "$OUT/summary.txt" 2>&1
echo DONE
