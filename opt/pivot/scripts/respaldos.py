#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Respaldos del Leelbox.

  respaldos.py db       -> copia sqlite segura de cada base (retiene 7 dias)
  respaldos.py sistema  -> tarball de codigo+config (retiene 4 semanas)

Cron en /etc/cron.d/pivot-mantenimiento:
  db diariamente 23:00, sistema los domingos 03:30.
"""
import datetime
import glob
import os
import sqlite3
import subprocess
import sys

DEST = "/var/backups/pivot"
RETENCION_DB = 7
RETENCION_TAR = 4

CONTENIDO_SISTEMA = [
    "/opt/pivot",
    "/opt/leelbox-monitor/leelbox-monitor.py",
    "/etc/pivot-ntfy.env",
    "/etc/ntfy/server.yml",
    "/etc/systemd/system/pivot.service.d",
    "/etc/cron.d/pivot-reporte",
    "/etc/cron.d/pivot-mantenimiento",
    "/boot/armbianEnv.txt",
    "/etc/leelbox-monitor.token",
]


def respaldo_db():
    destino_dir = os.path.join(DEST, "db")
    os.makedirs(destino_dir, exist_ok=True)
    hoy = datetime.date.today().isoformat()
    hechos = []
    for db in sorted(glob.glob("/opt/pivot/pivotradar_data/*/pivot_core.db")):
        activo = db.split("/")[-2]
        destino = os.path.join(destino_dir, "%s-%s.db" % (activo, hoy))
        src = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        dst = sqlite3.connect(destino)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        hechos.append(destino)
        viejos = sorted(glob.glob(os.path.join(destino_dir, "%s-*.db" % activo)))
        for v in viejos[:-RETENCION_DB]:
            os.remove(v)
    print("respaldados:", ", ".join(hechos) if hechos else "(ninguna base encontrada)")


def respaldo_sistema():
    os.makedirs(DEST, exist_ok=True)
    hoy = datetime.date.today().strftime("%Y%m%d")
    tarball = os.path.join(DEST, "sistema-%s.tar.gz" % hoy)
    cmd = ["tar", "czf", tarball,
           "--exclude", "/opt/pivot/pivotradar_data"] + CONTENIDO_SISTEMA
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode not in (0, 1):   # 1 = algun archivo cambio al leerlo (tolerable)
        print("tar fallo: %s" % r.stderr[-400:])
        sys.exit(1)
    os.chmod(tarball, 0o600)
    viejos = sorted(glob.glob(os.path.join(DEST, "sistema-*.tar.gz")))
    for v in viejos[:-RETENCION_TAR]:
        os.remove(v)
    print("tarball: %s (%d KB)" % (tarball, os.path.getsize(tarball) // 1024))


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else ""
    if modo == "db":
        respaldo_db()
    elif modo == "sistema":
        respaldo_sistema()
    else:
        print("uso: respaldos.py db|sistema")
        sys.exit(2)