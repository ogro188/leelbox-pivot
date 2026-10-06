#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vigia del Leelbox: vigila Tailscale y el feed Deriv.

Corre por cron cada 5 min (/etc/cron.d/pivot-mantenimiento).

1. Tailscale offline 3 chequeos seguidos (15 min) -> reinicia tailscaled
   (max 1 reinicio cada 30 min para no entrar en bucle).
2. En horario de mercado, si NINGUN activo recibe ticks hace 15 min
   (o la API no responde) -> reinicia pivot.service (max 3 veces/dia).
   Fuera de horario (noches, findes, break 21:00-22:00 UTC) no actua.
Cada accion automatica se avisa por ntfy (topic radar_test).
"""
import base64
import datetime
import json
import os
import subprocess
import urllib.request

ENV_FILE = "/etc/pivot-ntfy.env"
STATE_FILE = "/var/lib/pivot/vigia.json"
TOPIC = "radar_test"
FALLOS_PARA_ACTUAR = 3            # 3 chequeos x 5 min = 15 min
MAX_TS_RESTART_MIN = 30
MAX_PIVOT_RESTARTS_DIA = 3


def _estado_cargar():
    try:
        with open(STATE_FILE) as f:
            e = json.load(f)
    except Exception:
        e = {}
    e.setdefault("ts_fallos", 0)
    e.setdefault("deriv_fallos", 0)
    e.setdefault("ts_ultimo_restart", 0)
    e.setdefault("piv_reinicios", {"fecha": "", "n": 0})
    return e


def _estado_guardar(e):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(e, f)
    os.replace(tmp, STATE_FILE)


def _credenciales():
    user = pwd = None
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("NTFY_USER="):
                    user = line.split("=", 1)[1]
                elif line.startswith("NTFY_PASS="):
                    pwd = line.split("=", 1)[1]
    except OSError:
        pass
    return user, pwd


def avisar(titulo, cuerpo, prio="default"):
    user, pwd = _credenciales()
    if not user or not pwd:
        print("ntfy: sin credenciales, solo log")
        return
    token = base64.b64encode(("%s:%s" % (user, pwd)).encode()).decode()
    req = urllib.request.Request("http://127.0.0.1:8081/%s" % TOPIC,
                                 data=cuerpo.encode(), method="POST")
    req.add_header("Title", titulo)
    req.add_header("Priority", prio)
    req.add_header("Authorization", "Basic " + token)
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print("ntfy fallo: %s" % e)


def mercado_abierto():
    """L-V excluyendo el break diario 21:00-22:00 UTC."""
    ahora = datetime.datetime.now(datetime.timezone.utc)
    if ahora.weekday() >= 5:
        return False
    if ahora.hour == 21:
        return False
    return True


def tailscale_mal():
    try:
        out = subprocess.run(["tailscale", "status", "--json"],
                             capture_output=True, text=True, timeout=30)
        d = json.loads(out.stdout or "{}")
        selfn = d.get("Self") or {}
        online = selfn.get("Online")
        backend = d.get("BackendState")
        mal = (online is False) or (backend not in ("Running",))
        return mal, "online=%s backend=%s" % (online, backend)
    except Exception as e:
        return True, "error: %s" % e


def reiniciar_unidad(unidad):
    r = subprocess.run(["systemctl", "restart", unidad],
                       capture_output=True, text=True, timeout=90)
    return r.returncode == 0


def chequeo_tailscale(e):
    mal, detalle = tailscale_mal()
    ahora = datetime.datetime.now().timestamp()
    if not mal:
        if e["ts_fallos"]:
            print("tailscale: recuperado tras %d fallos" % e["ts_fallos"])
        e["ts_fallos"] = 0
        print("tailscale: OK")
        return
    e["ts_fallos"] += 1
    print("tailscale: fallo %d/%d (%s)" % (e["ts_fallos"], FALLOS_PARA_ACTUAR, detalle))
    if e["ts_fallos"] < FALLOS_PARA_ACTUAR:
        return
    if ahora - e["ts_ultimo_restart"] < MAX_TS_RESTART_MIN * 60:
        print("tailscale: reinicio reciente, espero")
        return
    ok = reiniciar_unidad("tailscaled")
    e["ts_ultimo_restart"] = ahora
    e["ts_fallos"] = 0
    if ok:
        avisar("Vigia: Tailscale reiniciado",
               "Estaba offline (%s). Reiniciado automaticamente." % detalle)
        print("tailscale: REINICIADO")
    else:
        avisar("Vigia: FALLO al reiniciar Tailscale", detalle, prio="high")


def chequeo_deriv(e):
    if not mercado_abierto():
        e["deriv_fallos"] = 0
        print("deriv: mercado cerrado, no se exige ticks")
        return
    ticks = None
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8000/api/deriv/status",
                                   timeout=10)
        d = json.loads(r.read())
        ticks = [bool(a.get("tick_reciente"))
                 for a in (d.get("assets") or {}).values()]
    except Exception as err:
        print("deriv: API inaccesible: %s" % err)
    if ticks and any(ticks):
        e["deriv_fallos"] = 0
        print("deriv: OK (ticks vivos)")
        return
    e["deriv_fallos"] += 1
    motivo = "sin ticks en ningun activo" if ticks is not None else "API sin respuesta"
    print("deriv: fallo %d/%d (%s)" % (e["deriv_fallos"], FALLOS_PARA_ACTUAR, motivo))
    if e["deriv_fallos"] < FALLOS_PARA_ACTUAR:
        return
    hoy = datetime.date.today().isoformat()
    if e["piv_reinicios"].get("fecha") != hoy:
        e["piv_reinicios"] = {"fecha": hoy, "n": 0}
    if e["piv_reinicios"]["n"] >= MAX_PIVOT_RESTARTS_DIA:
        avisar("Vigia: feed Deriv sigue sin datos",
               "%s tras %d reinicios hoy. Requiere revision manual." % (
                   motivo, e["piv_reinicios"]["n"]), prio="high")
        return
    ok = reiniciar_unidad("pivot")
    e["deriv_fallos"] = 0
    if ok:
        e["piv_reinicios"]["n"] += 1
        avisar("Vigia: feed Deriv reiniciado",
               "%s durante 15 min. pivot.service reiniciado (intento %d/%d hoy)." % (
                   motivo, e["piv_reinicios"]["n"], MAX_PIVOT_RESTARTS_DIA))
        print("deriv: PIVOT REINICIADO")
    else:
        avisar("Vigia: FALLO al reiniciar pivot", motivo, prio="high")


def main():
    e = _estado_cargar()
    chequeo_tailscale(e)
    chequeo_deriv(e)
    _estado_guardar(e)


if __name__ == "__main__":
    main()