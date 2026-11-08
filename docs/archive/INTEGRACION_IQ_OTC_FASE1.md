# Integración IQ Option OTC — Fase 1 (collector read-only)

**Estado:** fase 1 cerrada. El collector de producción corre en el host-de-producción;
este documento describe el collector y su esquema. Ver
[`INTEGRACION_IQ_OTC_FASE2.md`](INTEGRACION_IQ_OTC_FASE2.md) para el runtime
integrado al motor y el despliegue.
**Alcance:** solo datos. No hay órdenes, ejecución, bots ni login.

## Qué hace

- Consulta el GraphQL público de IQ Option (`api.iqoption.com/v1/fininfo/graphql`).
- No usa API key, cookie, SSID ni cuenta.
- Recolecta `EURUSD-OTC` (ID 76) y `XAUUSD-OTC` (ID 1857).
- El OTC es sintético: estos datos son insumo de investigación, no precios de
  mercado real y no se mezclan con los símbolos reales.
- Guarda ticks con bid/ask, payout Turbo/Binary, sessionStat y latencia.
- Construye velas **M1** y **M15** alineadas a UTC.
- Exporta CSV con el formato que consume el backtest de PIVOT.
- Envía alertas de salud a ntfy con un topic propio.
- No toca `activos/`, no arranca `DerivRuntime`, no genera señales y no escribe en `senales_core`.

## Archivos

| Archivo | Función |
|---|---|
| `kernel/feeds/iqoption_public.py` | Cliente GraphQL, normalización y `BarBuilder` |
| `scripts/iq_public_collector.py` | CLI, SQLite, health, ntfy y exportación |
| `tests/unit/test_iq_public.py` | Tests de parseo y velas (sin red) |
| `deploy/iq-public-collector.service` | Unidad systemd de usuario |
| `data/iq_public/iq_public.db` | Base de datos del collector |
| `data/iq_public/export/*.csv` | Export para backtest |

## Servicio systemd (fase 1, PC)

> En producción el collector corre en el host-de-producción como servicio de sistema
> (`iq-public-collector.service`, root) y escribe en
> `$PIVOT_ROOT/pivotradar_data/iq_public/`. Esta sección queda como referencia
> de la instalación original en el PC.

El collector corre como servicio de usuario, habilitado al arranque y con
`Restart=always`. No requiere sudo.

```bash
systemctl --user status iq-public-collector
journalctl --user -u iq-public-collector -f
systemctl --user restart iq-public-collector
systemctl --user stop iq-public-collector
systemctl --user disable iq-public-collector
```

La unidad instalada está en
`~/.config/systemd/user/iq-public-collector.service` y la copia versionada en
`deploy/iq-public-collector.service`. Para reinstalarla:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/iq-public-collector.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now iq-public-collector
```

## Uso manual

```bash
cd $PIVOT_ROOT

# Una consulta de prueba
.venv/bin/python scripts/iq_public_collector.py --once

# Bucle continuo
.venv/bin/python scripts/iq_public_collector.py --loop

# Estado
.venv/bin/python scripts/iq_public_collector.py --status

# Calidad: gaps, cobertura de velas y salud 24h
.venv/bin/python scripts/iq_public_collector.py --quality

# Exportar CSV
.venv/bin/python scripts/iq_public_collector.py --export

# Probar ntfy
.venv/bin/python scripts/iq_public_collector.py --ntfy-test
```

Opciones útiles:

```bash
--ids 76,1857
--interval 1.0
--timeout 20
--stale-after 60
--health-every 60
--keep-ticks-days 14
--since-hours 0
--ntfy-topic pivot_EJEMPLO_OTC_health
--no-ntfy
```

Variables de entorno equivalentes:

```bash
IQ_PUBLIC_ACTIVE_IDS=76,1857
IQ_PUBLIC_INTERVAL=1.0
IQ_PUBLIC_TIMEOUT=20
IQ_PUBLIC_DB=data/iq_public/iq_public.db
IQ_PUBLIC_EXPORT_DIR=data/iq_public/export
IQ_PUBLIC_NTFY_TOPIC=pivot_EJEMPLO_OTC_health
IQ_PUBLIC_NTFY_SERVER=http://127.0.0.1:8081
IQ_PUBLIC_NTFY_USER=<usuario>
IQ_PUBLIC_NTFY_PASS=...
IQ_PUBLIC_STALE_AFTER=60
IQ_PUBLIC_KEEP_TICKS_DAYS=14
```

`IQ_PUBLIC_NTFY_USER` y `IQ_PUBLIC_NTFY_PASS` son opcionales y caen a
`NTFY_USER`/`NTFY_PASS`. En el host-de-producción el servidor es el ntfy local
(`http://127.0.0.1:8081`), con autenticación Basic, y la unidad carga
`/etc/pivot-ntfy.env`.

El servicio systemd carga opcionalmente `$PIVOT_ROOT/.env.iq_public` con
esas variables, sin necesidad de editar la unidad.

## Esquema SQLite

### `ticks`

Una fila por activo y muestra. `ts` es hora local de recepción en epoch UTC
(`ts_source='local_receive'`); la API no devuelve timestamp de servidor.
`latency_ms` permite ajustar el análisis a posteriori.

### `bars`

Velas cerradas M1/M15. Columnas OHLC, bid/ask de apertura/cierre, cantidad de
ticks y primer/último tick. `open_time` es epoch UTC.

No se inventan velas en huecos. El collector persiste únicamente velas
cerradas; la vela en curso vive en memoria y se descarta al reiniciar (queda
reflejada en el log como "velas en curso descartadas"). Una vela con pocos
ticks (por ejemplo, la primera tras arrancar el collector) se puede filtrar por
la columna `ticks`. La tabla `bars` tiene una clave primaria
`(active_id, timeframe, open_time)` y `upsert_bars` fusiona si el mismo bucket
se escribiera dos veces: conserva la primera apertura, combina máximo/mínimo y
suma las muestras.

### `collector_health`

Un registro cada `--health-every` segundos y al cerrar. Incluye estado,
antigüedad del activo más atrasado, latencia, requests, errores y totales.

Los ticks crudos se podan cada hora después de `--keep-ticks-days` (default 14).
Las velas M1/M15 no se borran: son la serie que se usará para el motor y el
backtest.

## ntfy

Topic propio: `pivot_EJEMPLO_OTC_health` (configurable con `IQ_PUBLIC_NTFY_TOPIC`).
En el host-de-producción apunta al ntfy local (`http://127.0.0.1:8081`), el mismo servidor
que las alertas reales, autenticado con `NTFY_USER`/`NTFY_PASS`.
No usa `pivot_EJEMPLO_XAUUSD` ni `pivot_EJEMPLO_EURUSD` para no mezclar salud del collector con
señales de mercado.

Eventos:

- inicio del collector;
- sin datos frescos (`stale`);
- 3+ fallos consecutivos (`error`);
- recuperación;
- detención.

Los errores se repiten como máximo cada 15 minutos. `--ntfy-test` envía un
mensaje de prueba.

## Validación de calidad

`--quality` resume en una pasada:

- intervalo medio y máximo entre ticks por activo;
- gaps mayores de 5 s y de 15 s;
- salto máximo de precio (detección de valores absurdos);
- frescura del último tick;
- cobertura de velas M1/M15 frente al rango temporal almacenado;
- muestras mínima/media/máxima por vela;
- eventos `error`/`stale` de las últimas 24 h.

La cobertura baja al principio es esperable: el rango incluye el hueco del
reinicio del equipo. Para la validación de 72 h se ejecuta con
`--since-hours 72`, que ignora ese tramo y exige cobertura ≥95 %, cero gaps
>15 s y cero eventos `error`/`stale` en la ventana.

```bash
.venv/bin/python scripts/iq_public_collector.py --quality --since-hours 72
```

## Limitaciones

- El endpoint es no oficial y puede cambiar o limitar tasa.
- No entrega velas OHLC ni historial profundo.
- Las velas M1/M15 se construyen desde muestras puntuales; son aproximaciones,
  no OHLC de exchange. Los wicks dependen de la frecuencia de polling.
- La primera petición de una sesión HTTP nueva puede tardar 5–10 s por TLS/DNS;
  las siguientes reutilizan la conexión y suelen tardar 0,3–1 s.
- `volume=0` en los CSV: IQ no entrega volumen para OTC. La columna `ticks`
  indica cuántas muestras tuvo la vela.
- El collector corre como servicio systemd de usuario con `Restart=always` y
  `linger=yes`, por lo que sobrevive reinicios y caídas del proceso. Los logs
  van al journal (`journalctl --user -u iq-public-collector`).

## Fase 2 (implementada)

El collector de producción corre en el host-de-producción como servicio de sistema
(`iq-public-collector.service`) y escribe en
`$PIVOT_ROOT/pivotradar_data/iq_public/iq_public.db`. El runtime
`kernel/iq_public_runtime.py` lee esa SQLite en modo read-only y alimenta
`PivotRadarEngine`; las señales se guardan con `fuente='iqoption_public'` y los
símbolos `-OTC` siguen ocultos del panel.

Detalle de arquitectura, rutas, endpoints, servicios y validación:
[`INTEGRACION_IQ_OTC_FASE2.md`](INTEGRACION_IQ_OTC_FASE2.md).

## Limitaciones de histórico

Con la restricción actual de **cero autenticación**, la única fuente histórica
viable es la recolección forward:

- M15: ~14 h para 55 velas.
- H4: ~8,3 días para 50 velas.
- D1: ~205 días para 205 velas (EMA200).

OTCharts (API key) y la demo de IQ (login) quedan descartados hasta que se
autorice explícitamente una credencial. Sin eso, el motor puede arrancar en
caliente con M15/H4, pero `trend_d1` quedará `NEUTRO` durante meses.
