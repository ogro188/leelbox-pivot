#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reporte diario de senales publicado por ntfy.

Calcula el acierto real por detector y por banda de confianza declarada,
usando mediciones sobre velas CERRADAS (tabla senales_resultados), y lo
publica en un topic de ntfy con las credenciales de /etc/pivot-ntfy.env.

  python3 scripts/reporte_diario.py            # publica
  python3 scripts/reporte_diario.py --dry      # solo imprime
"""
import base64
import datetime
import glob
import os
import sqlite3
import sys
import urllib.request

BREAK_EVEN = 100.0 / 1.85          # payout 85% -> 54.1%
ENV_FILE = "/etc/pivot-ntfy.env"
TOPIC = os.getenv("REPORTE_TOPIC", "radar_test")
MIN_N = 5                          # por debajo de esto no se marca rojo


def credenciales():
    user = pwd = None
    try:
        with open(ENV_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("NTFY_USER="):
                    user = line.split("=", 1)[1].strip()
                elif line.startswith("NTFY_PASS="):
                    pwd = line.split("=", 1)[1].strip()
    except OSError:
        pass
    return user or os.getenv("NTFY_USER"), pwd or os.getenv("NTFY_PASS")


def datos(horizonte=1):
    por_det = {}
    por_banda = {}
    medidas = 0
    total = 0
    hoy = 0
    for db in sorted(glob.glob("/opt/pivot/pivotradar_data/*/pivot_core.db")):
        activo = db.split("/")[-2].upper()
        try:
            c = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        except sqlite3.Error:
            continue
        total += c.execute("select count(*) from senales_core").fetchone()[0]
        hoy += c.execute(
            "select count(*) from senales_core where date(created_at)=date('now')").fetchone()[0]
        q = """
            SELECT s.detector, s.hipotesis_prob_min, r.retorno
            FROM senales_core s
            JOIN senales_resultados r ON r.signal_id = s.signal_id
            WHERE r.horizonte = ?
        """
        for det, pmin, ret in c.execute(q, (horizonte,)):
            medidas += 1
            ok = 1 if (ret or 0) > 0 else 0
            d = por_det.setdefault(det or "?", [0, 0])
            d[0] += 1
            d[1] += ok
            banda = int((pmin or 0) // 10) * 10
            b = por_banda.setdefault(banda, [0, 0])
            b[0] += 1
            b[1] += ok
        c.close()
    return por_det, por_banda, medidas, total, hoy


def linea(nombre, par):
    n, wins = par
    pct = 100.0 * wins / n if n else 0.0
    if n < MIN_N:
        marca = "⚠️"
    elif pct < BREAK_EVEN:
        marca = "❌"
    else:
        marca = "✅"
    return "  %-16s %3d señales · %5.1f%% %s" % (nombre, n, pct, marca)


def construir():
    por_det, por_banda, medidas, total, hoy = datos(1)
    medidas2 = datos(2)[2]
    f = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    m = ["# 📊 Reporte diario PIVOT — %s" % f, ""]
    m.append("**Señales:** %d acumuladas · %d hoy" % (total, hoy))
    m.append("**Con resultado medido:** %d (h1) · %d (h2)" % (medidas, medidas2))
    m.append("")
    m.append("## 🎯 Acierto por detector")
    m.append("*cierre de la vela siguiente en la dirección anunciada*")
    if por_det:
        for det in sorted(por_det, key=lambda k: -por_det[k][0]):
            m.append(linea(det, por_det[det]))
    else:
        m.append("  (sin datos)")
    m.append("")
    m.append("## 🏷️ Por confianza declarada")
    if por_banda:
        for b in sorted(por_banda, reverse=True):
            m.append(linea("%d-%d%%" % (b, b + 9), por_banda[b]))
    else:
        m.append("  (sin datos)")
    m.append("")
    m.append("💡 **Break-even** con payout 85%%: **%.1f%%**" % BREAK_EVEN)
    if medidas < 100:
        m.append("⚠️ Muestra todavía pequeña: no es concluyente hasta n≥30 por detector.")
    return "\n".join(m)


def publicar(mensaje):
    user, pwd = credenciales()
    if not user or not pwd:
        return False, "sin credenciales en %s" % ENV_FILE
    url = "http://127.0.0.1:8081/%s" % TOPIC
    token = base64.b64encode(("%s:%s" % (user, pwd)).encode()).decode()
    req = urllib.request.Request(url, data=mensaje.encode("utf-8"), method="POST")
    req.add_header("Title", "PIVOT - reporte diario")
    req.add_header("Priority", "default")
    req.add_header("Tags", "bar_chart")
    req.add_header("Authorization", "Basic " + token)
    req.add_header("Content-Type", "text/markdown; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return True, "HTTP %d" % r.status
    except Exception as e:                      # noqa: BLE001
        return False, str(e)


def main():
    mensaje = construir()
    print(mensaje)
    print("\n" + "-" * 60)
    if "--dry" in sys.argv:
        return
    ok, detalle = publicar(mensaje)
    print("Publicado en ntfy topic '%s': %s %s" % (TOPIC, "OK" if ok else "FALLO", detalle))
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()