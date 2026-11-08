# Integración IQ Option OTC — Fase 2 (runtime en el host-de-producción)

**Estado:** desplegado y en ejecución en `host-de-producción` desde el
2026-11-01 01:08 UTC.
**Alcance:** solo datos e investigación. No hay órdenes, ejecución, bots ni
login. El OTC es sintético: no se mezcla con los símbolos reales.

## Arquitectura

```text
GraphQL público IQ Option
        │  (sin API key, cookie, SSID ni cuenta)
        ▼
iq-public-collector.service  (systemd, host-de-producción)
        │  ticks + velas M1/M15 cerradas
        ▼
$PIVOT_ROOT/pivotradar_data/iq_public/iq_public.db   (SQLite persistente)
        │  lectura read-only, cada 5 s
        ▼
kernel/iq_public_runtime.py
        │  M15 cerradas + H1/H4/D1 resampleados
        ▼
PivotRadarEngine (core/motor_v8.py)
        │  señales
        ├──► senales_core (fuente='iqoption_public')
        └──► WebSocket solo si activo.visible == true
```

El collector es el **único** proceso que consulta IQ Option. El runtime de la
API no hace red hacia IQ: solo lee la SQLite. Esto evita duplicar polling y
mantiene el collector aislado del ciclo de vida de `pivot.service`.

## Componentes

| Archivo / ruta | Función |
|---|---|
| `kernel/feeds/iqoption_public.py` | Cliente GraphQL y `BarBuilder` |
| `scripts/iq_public_collector.py` | Collector, SQLite, salud y export |
| `kernel/iq_public_runtime.py` | Runtime OTC: SQLite → motor → señales |
| `kernel/api/app.py` | Lifespan, `/api/health`, `/api/assets`, `/history`, start/stop |
| `activos/eurusd-otc.json` | `EURUSD-OTC`, ID 76, `visible: false` |
| `activos/xauusd-otc.json` | `XAUUSD-OTC`, ID 1857, `visible: false` |
| `deploy/iq-public-collector-host-de-producción.service` | Unidad systemd del collector |
| `deploy/pivot-otc.conf` | Drop-in de `pivot.service` |

## Rutas persistentes en el host-de-producción

```text
$PIVOT_ROOT/pivotradar_data/iq_public/iq_public.db   # collector (persistente)
$PIVOT_ROOT/pivotradar_data/iq_public/export/        # CSV opcional
$PIVOT_ROOT/pivotradar_data/eurusd-otc/pivot_core.db # estado interno del motor
$PIVOT_ROOT/pivotradar_data/xauusd-otc/pivot_core.db
```

No se usa `$PIVOT_ROOT/data` para el collector: ese path es un symlink a
un directorio temporal y se pierde al reiniciar.

Las señales OTC se guardan en la misma base `pivot.db` del PIVOT
(un archivo SQLite temporal en el host-de-producción, vía `data/pivot.db`), con
`symbol` terminado en `-OTC` y `fuente='iqoption_public'`. Es la base histórica
del sistema; el sufijo `-OTC` es obligatorio para separar.

## Servicios

```bash
# Collector OTC (systemd de sistema, root)
systemctl status iq-public-collector
journalctl -u iq-public-collector -f
systemctl restart iq-public-collector

# API PIVOT (incluye el runtime OTC)
systemctl status pivot
journalctl -u pivot -f
systemctl restart pivot
```

El drop-in `pivot.service.d/iq-public.conf` define:

```ini
Environment=IQ_PUBLIC_DB=$PIVOT_ROOT/pivotradar_data/iq_public/iq_public.db
Environment=IQ_PUBLIC_RUNTIME_POLL=5
Environment=IQ_PUBLIC_ENGINE_DATA_DIR=$PIVOT_ROOT/pivotradar_data
Environment=IQ_PUBLIC_SIGNALS_NTFY_TOPIC=
Environment=IQ_PUBLIC_SIGNALS_NTFY_SERVER=http://127.0.0.1:8081
```

Cada activo define su topic y servidor en su JSON:

| Activo | Topic | Servidor |
|---|---|---|
| `EURUSD-OTC` | `pivot_EJEMPLO_EURUSD` | `http://127.0.0.1:8081` |
| `XAUUSD-OTC` | `pivot_EJEMPLO_XAUUSD` | `http://127.0.0.1:8081` |

El servidor es el ntfy local del host-de-producción, el mismo que usan los activos reales.
La autenticación sale de `/etc/pivot-ntfy.env` (`NTFY_USER` y `NTFY_PASS`), que
ya carga `pivot.service`.

El celular entra por el Funnel con el usuario `host-de-producción` y mantiene una única
suscripción WebSocket a `pivot_EJEMPLO_EURUSD,pivot_EJEMPLO_XAUUSD`. Por eso las señales OTC se
publican en esos mismos topics: la entrega al celular tiene prioridad sobre la
separación de topics. El símbolo completo viaja en el título y en el cuerpo
(`CALL - EURUSD-OTC - D2_ANTICIPACION`), así que la notificación no es ambigua.
Los topics dedicados `pivot_OTC_EURUSD` y `pivot_OTC_XAUUSD` existen con ACL
(escritura para `alertas`, lectura para `laptop`), pero no se usan mientras el
celular no esté suscripto a ellos. Si se agregan esas suscripciones en la app
ntfy, alcanza con cambiar `ntfy.topic` en cada JSON y reiniciar `pivot.service`.

La salud del collector usa `pivot_EJEMPLO_OTC_health` en el mismo servidor local, con
las mismas credenciales. Para silenciar las señales OTC alcanza con dejar
`ntfy.topic` vacío en el JSON del activo y reiniciar `pivot.service`.

La autenticación Basic se agrega en la versión del host-de-producción de
`core/alertas.py` y en el notifier del collector; no sobrescribir esos archivos
con copias del repo que no incluyan auth.

## API

- `GET /api/health` incluye `iq_public` con:
  - `db`, `db_exists`, `connected`;
  - `collector`: último registro de salud (estado, edad, errores, requests);
  - `assets`: por símbolo, velas en buffer, `engine_ready`, precio, edad de la
    última vela/tick, señales emitidas, `ntfy_topic`, `ntfy_server`,
    `ntfy_ready` y último error.
- `GET /api/assets` **excluye** los activos con `visible: false`. Por eso
  `EURUSD-OTC` y `XAUUSD-OTC` no aparecen en el hub ni en el selector.
- `GET /api/assets/{simbolo}/history?tf=M15|H1|H4|D1&count=N` funciona también
  para los OTC ocultos, para inspección directa.
- `POST /api/assets/{simbolo}/start|stop` detecta `fuente_tipo=iqoption_public`
  y **no** lanza replay CSV; devuelve el estado del runtime OTC en modo
  read-only.

## Comportamiento del runtime

- Al arrancar carga las M15 cerradas del collector y precalienta el motor con
  alertas silenciadas. Las señales del histórico no se persisten ni se envían.
- Solo alimenta al motor cuando el collector escribe una M15 cerrada. No usa la
  vela en curso.
- H1/H4/D1 se resamplean desde el buffer M15; no hay fuente histórica superior.
- Si detecta un hueco mayor a 30 min en el buffer, descarta el tramo anterior y
  reinicia el motor para no encadenar velas no consecutivas. La reconstrucción
  se ejecuta con `asyncio.to_thread` porque `PivotRadarEngine` crea su propio
  event loop al cargar la cola pendiente; construirla dentro del loop de la API
  fallaba con `Cannot run the event loop while another loop is running` y dejaba
  el stream en `engine=None`. Si la construcción falla, se reintenta en el
  siguiente `poll`.
- Una vela que llega con más de 30 min de atraso se usa para indicadores, pero
  no emite señales.
- Las señales nuevas se persisten siempre con `fuente='iqoption_public'`.
  Solo se difunden por WebSocket si el activo tiene `visible: true`.

## Validación

La ventana de 72 h arranca con el collector del host-de-producción:

- inicio: **2026-11-01 01:08 UTC**;
- fin: **2026-11-04 01:10 UTC**.

Al cumplirse:

```bash
cd $PIVOT_ROOT
PYTHONPATH=$PIVOT_ROOT python3 scripts/iq_public_collector.py \
  --quality --since-hours 72 \
  --db $PIVOT_ROOT/pivotradar_data/iq_public/iq_public.db
```

Criterio: cobertura ≥95 %, cero gaps >15 s, cero eventos `error`/`stale` y CSV
exportable. Si pasa, se decide si se hace visible el OTC en el panel.

Las notificaciones de señales OTC ya están activas en el ntfy local, en los
topics que el celular ya escucha (`pivot_EJEMPLO_EURUSD`, `pivot_EJEMPLO_XAUUSD`), con el
símbolo `-OTC` en el título. El panel sigue oculto: visibilidad y
notificaciones son decisiones independientes.

El histórico copiado desde el PC contiene un corte de 11,2 h (el PC estuvo
apagado/suspendido). El runtime lo detecta y conserva solo la racha continua
final; por eso al desplegar quedaron 48 velas M15 en buffer y `engine_ready`
pasa a `true` al llegar a 55 (unas 7 velas después).

## Limitaciones

- Sin autenticación no hay OHLC histórico profundo. M15 tarda ~14 h en tener 55
  velas; H4 ~8,3 días para 50; D1 ~205 días para 205. `trend_d1` quedará
  `NEUTRO` durante meses.
- Las velas se construyen desde muestras puntuales (~1/s); los wicks dependen
  del polling. No son OHLC de exchange.
- El collector persiste solo velas cerradas: el chart OTC, cuando se haga
  visible, mostrará la última vela cerrada y no la formación en curso.
- El endpoint público es no oficial y puede cambiar o limitar tasa.

## Rollback

```bash
systemctl disable --now iq-public-collector
rm -f /etc/systemd/system/pivot.service.d/iq-public.conf
systemctl daemon-reload
systemctl restart pivot
```

El backup de `app.py` y `activos/` previo al despliegue está en
`backups/iq-otc-<fecha>/`. Los archivos nuevos (`iq_public_runtime.py`,
`iqoption_public.py`, `iq_public_collector.py`, `*-otc.json`) se pueden dejar:
sin el drop-in y sin el collector no se activan.
