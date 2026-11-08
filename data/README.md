# Datos

Velas OHLCV públicas de Deriv para EURUSD y XAUUSD. **No contienen datos personales, IDs de cuenta ni tokens.**

## Contenido

| Archivo | Velas | Rango UTC | Uso |
|---|---:|---|---|
| `eurusd_M15.csv` | 24.202 | 2025-11-07 03:00 → 2026-11-06 20:45 | Base del replay y de los escaneos de 12 meses. |
| `xauusd_M15.csv` | 23.140 | 2025-11-07 03:00 → 2026-11-06 20:45 | Ídem. |
| `eurusd_D1.csv` | 257 | 2025-11-10 → 2026-11-05 | Contexto D1 del replay. |
| `xauusd_D1.csv` | 256 | 2025-11-10 → 2026-11-05 | Ídem. |
| `eurusd_H1.csv` | 440 | 2026-10-13 03:00 → 2026-11-06 19:00 | Muestra reciente auxiliar. |
| `xauusd_H1.csv` | 425 | 2026-10-13 03:00 → 2026-11-06 19:00 | Muestra reciente auxiliar. |
| `eurusd_H4.csv` | 214 | 2026-09-18 04:00 → 2026-11-06 16:00 | Muestra reciente auxiliar. |
| `xauusd_H4.csv` | 214 | 2026-09-18 04:00 → 2026-11-06 16:00 | Muestra reciente auxiliar. |

**Importante:** los CSV H1/H4 **no** cubren 12 meses. Son las últimas páginas que devolvió la API para esos timeframes. El replay de `feature_replay.py` y los escaneos de 12 meses **derivan H1/H4 desde M15** con `kernel/feeds/csv_resample.py`; los CSV H1/H4 solo sirven como muestra de contraste. El D1 sí se usa tal cual.

## Esquema

```text
epoch,datetime,open,high,low,close,volume
```

| Columna | Tipo | Descripción |
|---|---|---|
| `epoch` | entero | Segundos desde 1970-01-01 UTC. |
| `datetime` | ISO 8601 | Inicio de la vela en UTC. |
| `open` | float | Primer precio de la vela. |
| `high` | float | Máximo de la vela. |
| `low` | float | Mínimo de la vela. |
| `close` | float | Último precio de la vela. |
| `volume` | float | Volumen/tick volume. Deriv devuelve 0 en forex; no usar como señal. |

- No hay duplicados de `epoch` ni valores nulos en M15.
- Los fines de semana no tienen velas; el eje temporal es continuo en horario de mercado.
- Las velas H1/H4/D1 se pueden derivar de M15; los CSV incluidos son una muestra auxiliar.

## Limitaciones

- **12 meses es el máximo** que devolvió la API de Deriv para M15. No hay 24 meses.
- El volumen de forex es 0; cualquier conclusión basada en volumen no es válida en estos CSV.
- Los precios son los del feed público de Deriv, no los de IQ Option ni los de un broker concreto.
- La historia OTC **no** está incluida: requiere el colector IQ Option y sus bases SQLite.
- La descarga de H1/H4 se truncó por paginación; no se usó para el análisis principal.

## Reproducir la descarga

```bash
python tools/fetch_history.py --symbol EURUSD --months 12 --out-dir data
python tools/fetch_history.py --symbol XAUUSD --months 12 --out-dir data
```

Requiere red y el feed de Deriv. No toca producción.
