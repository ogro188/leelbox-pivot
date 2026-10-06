# leelbox-pivot

Sistema de trading automatizado / detector de señales del Leelbox (ARM, armv7l, Debian).

## Estructura

| Ruta | Contenido |
|---|---|
| `opt/pivot/` | Código fuente del detector v8 (core/, kernel/, estrategias/, scripts/, tests/, docs/) |
| `opt/leelbox-monitor/` | Panel web de monitoreo del sistema |
| `etc/cron.d/` | Tareas programadas (reporte diario 22:30, vigía cada 5 min, backups) |
| `etc/systemd/system/pivot.service.d/` | Drop-ins de systemd |
| `etc/ntfy/server.yml` | Configuración del servidor de notificaciones |
| `boot/armbianEnv.txt` | Parámetros de arranque (HDMI desactivado, coherent_pool) |

## No incluido en este repo (por seguridad)

- `opt/pivot/.env` — credenciales de Deriv API
- `etc/pivot-ntfy.env`, `etc/leelbox-monitor.token` — credenciales ntfy y del panel
- `/etc/oscam.*`, `/opt/oscam` — configs con contraseñas del cardsharing
- Bases de datos (`opt/pivot/pivotradar_data/**/*.db`) — respaldadas aparte en
  `/var/backups/pivot/db/` (cron diario 23:00, retención 7 días)
- Tarball semanal del sistema completo (incluye secretos): `/var/backups/pivot/`

## Refresh

Re-sincronizar desde la caja y empujar:

```bash
ssh root@192.168.1.169 'cd / && tar cz --exclude="*/__pycache__" --exclude="*.bak*" \
  --exclude="opt/pivot/pivotradar_data" --exclude="opt/pivot/.env" --exclude="opt/oscam" \
  opt/pivot opt/leelbox-monitor etc/cron.d/pivot-reporte etc/cron.d/pivot-mantenimiento \
  etc/systemd/system/pivot.service.d etc/ntfy/server.yml boot/armbianEnv.txt' | tar xz
git add -A && git commit -m "refresh" && git push
```
