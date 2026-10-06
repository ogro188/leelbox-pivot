#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Monitoreo web del Leelbox: sistema + trading, en el movil.

Una sola pagina, pensada para pantalla de celular, que se actualiza sola.
Datos del sistema leidos de /proc y sysfs; datos del trading tomados de la
API local del sistema de trading (127.0.0.1:8000).

Solo libreria estandar del sistema mas fastapi/uvicorn (ya instalados por el
propio trading).
"""
import json
import os
import time
from collections import deque
from html import escape

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (HTMLResponse, JSONResponse,
                               RedirectResponse)

API_TRADING = "http://127.0.0.1:8000"
IFACE_WIFI = "wlx000f00aa63bb"
HIST = 180                      # muestras para los minigraficos
PUERTO = int(os.environ.get("LEELBOX_MONITOR_PORT", "8080"))
def _token():
    """Lee el token de /etc/leelbox-monitor.token (permisos 600, solo root)."""
    ruta = os.environ.get("LEELBOX_MONITOR_TOKEN_FILE",
                         "/etc/leelbox-monitor.token")
    try:
        with open(ruta) as f:
            return f.read().strip()
    except Exception:
        return os.environ.get("LEELBOX_MONITOR_TOKEN", "")


TOKEN = _token()

# Freno a la fuerza bruta contra /login: N fallos y la IP espera un rato.
INTENTOS_MAX = 8
INTENTOS_VENTANA = 900          # 15 minutos
_intentos = {}

app = FastAPI(title="Leelbox Monitor", docs_url=None, redoc_url=None)

# ------------------------------------------------------------------ helpers

_cache = {"t": 0.0, "data": None}
_precios = {}
_ultimo_precio = {}


def sh(cmd, timeout=5):
    try:
        import subprocess
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def leer_json(url, timeout=5):
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def human(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return "%.1f %s" % (n, u)
        n /= 1024.0
    return "%.1f PB" % n


def htime(sec):
    sec = int(sec or 0)
    d, sec = divmod(sec, 86400)
    h, sec = divmod(sec, 3600)
    m = sec // 60
    if d:
        return "%dd %dh" % (d, h)
    if h:
        return "%dh %dm" % (h, m)
    return "%dm" % m


# ------------------------------------------------------------------ sistema

def cpu_porcentaje():
    total = idle = 0
    try:
        with open("/proc/stat") as f:
            v = [int(x) for x in f.readline().split()[1:]]
        idle = v[3] + (v[4] if len(v) > 4 else 0)
        total = sum(v)
    except Exception:
        return None
    prev = _cache.get("cpu_prev")
    _cache["cpu_prev"] = (total, idle)
    if not prev or total <= prev[0]:
        return None
    dt = total - prev[0]
    return 100.0 * (dt - (idle - prev[1])) / dt if dt else None


def sistema():
    datos = {}
    datos["cpu"] = cpu_porcentaje()
    try:
        with open("/proc/loadavg") as f:
            l = f.read().split()[:3]
        datos["load"] = [float(x) for x in l]
    except Exception:
        datos["load"] = [0, 0, 0]
    datos["nucleos"] = os.cpu_count() or 1

    mem = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, rest = line.partition(":")
                mem[k] = int(rest.split()[0]) * 1024
    except Exception:
        pass
    tot = mem.get("MemTotal", 0)
    disp = mem.get("MemAvailable", mem.get("MemFree", 0))
    datos["mem"] = {"total": tot, "usada": tot - disp, "disp": disp,
                    "cache": mem.get("Cached", 0) + mem.get("Buffers", 0)}

    out = sh("df -B1 --output=size,used,avail / | tail -1")
    try:
        p = out.split()
        datos["disco"] = {"total": int(p[0]), "usada": int(p[1]),
                          "disp": int(p[2])}
    except Exception:
        datos["disco"] = {"total": 0, "usada": 0, "disp": 0}

    t = None
    for zp in ("/sys/class/thermal/thermal_zone0/temp",
               "/sys/class/thermal/thermal_zone1/temp"):
        try:
            with open(zp) as f:
                t = int(f.read().strip()) / 1000.0
            break
        except Exception:
            continue
    datos["temp"] = t

    try:
        with open("/proc/uptime") as f:
            datos["uptime"] = float(f.read().split()[0])
    except Exception:
        datos["uptime"] = 0

    ip = sh("ip -4 -o addr show %s | awk '{print $4}'" % IFACE_WIFI)
    datos["ip"] = ip.split("/")[0] if ip else "sin IP"
    m = sh("iw dev %s link | grep -m1 signal:" % IFACE_WIFI)
    import re
    mm = re.search(r"signal:\s*(-?\d+)", m)
    datos["senal"] = int(mm.group(1)) if mm else None
    datos["ssid"] = sh("iw dev %s link | grep -m1 SSID:" % IFACE_WIFI
                       ).split("SSID:")[-1].strip() or "-"
    datos["carga_disco"] = sh("df -h / | awk 'NR==2{print $5}'")
    return datos


# ------------------------------------------------------------------ trading

_SENALES = {"t": 0.0, "datos": None}


def _senales_cache():
    """Senales del trading, refrescadas como mucho cada 2 minutos."""
    ahora = time.time()
    if _SENALES["datos"] is not None and ahora - _SENALES["t"] < 120:
        return _SENALES["datos"]
    datos = []
    st = leer_json(API_TRADING + "/api/analitica/resumen", timeout=5)
    if isinstance(st, dict):
        for k in ("senales_hoy", "total_senales", "operaciones"):
            if k in st:
                datos.append({"etiqueta": k, "valor": st[k]})
    for sym in ("XAUUSD", "EURUSD"):
        d = leer_json(API_TRADING + "/api/assets/%s/signals" % sym, timeout=4)
        if isinstance(d, list) and d and isinstance(d[0], dict):
            u = d[0]
            val = u.get("direccion") or u.get("tipo") or u.get("senal") or "sí"
            extra = u.get("precio") or u.get("entry_price")
            if extra:
                val = "%s @ %s" % (val, extra)
            datos.append({"etiqueta": "%s última señal" % sym, "valor": val})
    _SENALES["t"] = ahora
    _SENALES["datos"] = datos
    return datos


def trading():
    ini = time.time()
    salud = leer_json(API_TRADING + "/api/health", timeout=6)
    lat = (time.time() - ini) * 1000.0
    if not salud:
        return {"ok": False, "latencia": None, "activos": [],
                "error": "la API del trading no responde"}

    der = salud.get("deriv") or {}
    activos = []
    for sym, a in (der.get("assets") or {}).items():
        s = _precios.setdefault(sym, deque(maxlen=HIST))
        if a.get("price") is not None:
            s.append(float(a["price"]))
        prec = 5 if sym.upper() == "EURUSD" else 2
        p0 = s[0] if s else None
        p1 = s[-1] if s else None
        activos.append({
            "simbolo": sym,
            "precio": a.get("price"),
            "decimales": prec,
            "conectado": bool(a.get("connected")),
            "corriendo": bool(a.get("running")),
            "tick_reciente": bool(a.get("tick_reciente")),
            "velas": a.get("velas_buffer", 0),
            "senales": a.get("señales_enviadas", 0),
            "error": a.get("last_error"),
            "variacion": (p1 - p0) if (p0 and p1) else None,
            "var_pct": (100.0 * (p1 - p0) / p0) if (p0 and p1) else 0.0,
            "min": min(s) if s else None,
            "max": max(s) if s else None,
            "hist": [round(x, prec) for x in list(s)[-90:]],
        })
    activos.sort(key=lambda x: x["simbolo"])

    # Las señales se piden poco: consultar esto en cada refresco (3 s) generaba
    # mucho ruido en el journal del trading y no aportaba nada nuevo.
    senales = _senales_cache()

    return {"ok": True, "latencia": lat, "conectado": bool(der.get("connected")),
            "version": salud.get("version"), "estado": salud.get("status"),
            "estrategias": salud.get("strategies_loaded"),
            "activos": activos, "senales": senales, "error": None}


# ------------------------------------------------------------------ wifi

CONF_WIFI = "/etc/wpa_supplicant/wpa_supplicant-%s.conf" % IFACE_WIFI


def wifi_ssid_actual():
    """SSID configurado en la caja (puede estar entre comillas)."""
    try:
        with open(CONF_WIFI) as f:
            txt = f.read()
    except Exception:
        return ""
    import re
    m = re.search(r'^\s*ssid\s*=\s*"?([^"\n]+)"?\s*$', txt, re.M)
    return m.group(1).strip() if m else ""


def wifi_estado():
    """Solo lectura: estado del enlace WiFi. No permite cambiar de red."""
    import re
    d = {"ssid": wifi_ssid_actual(), "ip": "", "senal": None,
         "conectado": False, "interfaz": IFACE_WIFI}
    link = sh("iw dev %s link" % IFACE_WIFI, timeout=5)
    if link and "Not connected" not in link:
        d["conectado"] = True
        m = re.search(r"SSID:\s*(.+)", link)
        if m:
            d["ssid"] = m.group(1).strip()
        m = re.search(r"signal:\s*(-?\d+)", link)
        if m:
            d["senal"] = int(m.group(1))
        m = re.search(r"bssid:\s*([0-9a-f:]+)", link)
        if m:
            d["bssid"] = m.group(1)
    o = sh("ip -4 -o addr show %s" % IFACE_WIFI, timeout=5)
    if o:
        d["ip"] = o.split()[3].split("/")[0]
    return d


# ------------------------------------------------------------------ ap propio

IFACE_AP = "wlx6466b3089e90"
CONF_AP = "/etc/hostapd/hostapd.conf"

# Redes que ya se han conectado una vez: se guarda la clave para no
# escribirla de nuevo cada vez. Solo root puede leerlo.
RUTA_CONOCIDAS = "/etc/wpa_supplicant/redes-conocidas.json"


def redes_conocidas():
    try:
        with open(RUTA_CONOCIDAS) as f:
            return json.load(f)
    except Exception:
        return {}


def guardar_red(ssid, clave):
    d = redes_conocidas()
    d[ssid] = clave
    with open(RUTA_CONOCIDAS, "w") as f:
        json.dump(d, f, indent=1)
    try:
        os.chmod(RUTA_CONOCIDAS, 0o600)
    except Exception:
        pass


def wifi_escanear():
    """Lista de redes visibles, ordenada por senal.

    Escanea sobre el mismo dongle que da internet, asi que la conexion
    actual puede parpadear un momento durante el escaneo.
    """
    import re
    salida = sh("iw dev %s scan" % IFACE_WIFI, timeout=30)
    if not salida or "command failed" in salida.lower():
        return []
    actual, redes = None, {}
    for linea in salida.splitlines():
        l = linea.strip()
        m = re.match(r"^BSS\s+([0-9a-f:]+)", l)
        if m:
            actual = {"bssid": m.group(1), "senal": None, "freq": 0,
                      "ssid": "", "seguro": False}
            continue
        if actual is None:
            continue
        if l.startswith("signal:"):
            try:
                actual["senal"] = round(float(l.split()[1]))
            except Exception:
                pass
        elif l.startswith("freq:"):
            try:
                actual["freq"] = int(float(l.split()[1]))
            except Exception:
                pass
        elif l.startswith("capability:"):
            actual["seguro"] = "Privacy" in l
        elif l.startswith("SSID:"):
            actual["ssid"] = l[5:].strip()
    # agrupar por SSID: nos quedamos con la senal mas fuerte
    for bloque in salida.split("BSS ")[1:]:
        m = re.search(r"^\s*signal:\s*(-?\d+(?:\.\d+)?)", bloque, re.M)
        senal = round(float(m.group(1))) if m else None
        m = re.search(r"^\s*SSID:\s*(.+)$", bloque, re.M)
        ssid = m.group(1).strip() if m else ""
        m = re.search(r"^\s*freq:\s*(\d+)", bloque, re.M)
        freq = int(m.group(1)) if m else 0
        segura = bool(re.search(r"^\s*capability:.*Privacy", bloque, re.M))
        if not ssid:
            continue
        previo = redes.get(ssid)
        if previo is None or (senal is not None and
                               (previo["senal"] is None or
                                senal > previo["senal"])):
            redes[ssid] = {"ssid": ssid, "senal": senal, "freq": freq,
                           "seguro": segura}
    lista = sorted(redes.values(),
                   key=lambda r: (r["senal"] is None, -(r["senal"] or -999)))
    for r in lista:
        r["conocida"] = r["ssid"] in redes_conocidas()
    return lista


def wifi_conectar(ssid, clave):
    """Escribe la config de wpa_supplicant y reinicia el cliente."""
    import subprocess
    if not ssid:
        return {"ok": False, "error": "falta el nombre de la red"}
    if clave and len(clave) < 8:
        clave = ""
    conf = ('ctrl_interface=DIR=/run/wpa_supplicant GROUP=netdev\n'
            'update_config=1\n'
            'country=CO\n'
            'network={\n'
            '\tssid="%s"\n' % ssid)
    if clave:
        conf += '\tpsk="%s"\n' % clave
    else:
        conf += '\tkey_mgmt=NONE\n'
    conf += '}\n'
    try:
        with open(CONF_WIFI, "w") as f:
            f.write(conf)
        os.chmod(CONF_WIFI, 0o600)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if clave:
        guardar_red(ssid, clave)
    subprocess.run("systemctl restart wpa_supplicant@%s" % IFACE_WIFI,
                   shell=True, capture_output=True, timeout=60)
    # esperar a que se asocie
    for _ in range(20):
        time.sleep(3)
        if sh("iw dev %s link" % IFACE_WIFI).find("Not connected") < 0:
            return {"ok": True, "ssid": ssid, "estado": wifi_estado()}
    return {"ok": False, "ssid": ssid,
            "error": "no se pudo conectar (clave incorrecta o sin cobertura)",
            "estado": wifi_estado()}



def _conf_ap(clave):
    """Lee una clave suelta del hostapd.conf."""
    import re
    try:
        with open(CONF_AP) as f:
            txt = f.read()
    except Exception:
        return ""
    m = re.search(r'^\s*%s\s*=\s*"?([^"\n]+)"?\s*$' % re.escape(clave), txt,
                  re.M)
    return m.group(1).strip() if m else ""


def ap_estado():
    """Estado del punto de acceso propio (RT3070). Solo el AP, no el WiFi WAN."""
    import re
    d = {"interfaz": IFACE_AP, "ssid": _conf_ap("ssid"),
         "canal": _conf_ap("channel"), "wpa": _conf_ap("wpa"),
         "activo": False, "estado": "detenido", "clientes": 0,
         "ip": "", "arrancando": False}
    d["activo"] = sh("systemctl is-active hostapd") == "active"
    d["arrancando"] = sh("systemctl is-active hostapd") in ("activating",
                                                            "deactivating")
    if d["activo"]:
        st = sh("hostapd_cli -p /var/run/hostapd -i %s status" % IFACE_AP,
                timeout=4)
        m = re.search(r"state=(\w+)", st)
        d["estado"] = m.group(1) if m else "ENABLED"
        cli = sh("hostapd_cli -p /var/run/hostapd -i %s all_sta" % IFACE_AP,
                 timeout=4)
        d["clientes"] = len([x for x in cli.split() if x.count(":") == 5])
    o = sh("ip -4 -o addr show %s" % IFACE_AP, timeout=4)
    if o:
        d["ip"] = o.split()[3].split("/")[0]
    d["dhcp"] = sh("grep -h ^dhcp-range /etc/dnsmasq.d/leelbox-ap.conf",
                   timeout=4)
    return d


# ------------------------------------------------------------------ endpoints

def estado():
    ahora = time.time()
    if _cache["data"] and ahora - _cache["t"] < 1.5:
        return _cache["data"]
    datos = {"ts": ahora, "sistema": sistema(), "trading": trading()}
    _cache["t"] = ahora
    _cache["data"] = datos
    return datos


def autorizado(req):
    if not TOKEN:
        return True
    cookie = req.cookies.get("leelbox", "")
    return cookie == TOKEN


@app.get("/api/estado")
async def api_estado(request: Request):
    if not autorizado(request):
        return JSONResponse({"error": "no autorizado"}, status_code=401)
    d = dict(estado())
    d["wifi"] = wifi_estado()
    d["ap"] = ap_estado()
    return JSONResponse(d)


@app.get("/api/wifi/redes")
async def api_redes(request: Request):
    """Escanea y devuelve las redes disponibles para conectarse."""
    if not autorizado(request):
        return JSONResponse({"error": "no autorizado"}, status_code=401)
    return JSONResponse({"redes": wifi_escanear(),
                         "actual": wifi_estado().get("ssid", "")})


@app.post("/api/wifi/conectar")
async def api_conectar(request: Request):
    """Cambia la red de internet a la elegida."""
    if not autorizado(request):
        return JSONResponse({"error": "no autorizado"}, status_code=401)
    try:
        cuerpo = await request.json()
    except Exception:
        cuerpo = {}
    r = wifi_conectar((cuerpo.get("ssid") or "").strip(),
                      cuerpo.get("clave") or "")
    return JSONResponse(r, status_code=200 if r.get("ok") else 400)


@app.post("/api/ap/{accion}")
async def api_ap(accion: str, request: Request):
    """Encendido / apagado / reinicio del AP propio.

    Importante: bajar la interfaz antes de arrancar. Este driver viejo
    (rt2800usb) devuelve EBUSY si hostapd encuentra la interfaz levantada, y
    ademas se queda duro si hay procesos hostapd huerfanos de una sesion
    anterior: por eso se limpian antes de arrancar.

    Devuelve de inmediato y deja el trabajo en segundo plano: si el celular
    esta conectado al propio AP, reiniciarlo corta la conexion y el navegador
    perderia la respuesta si esperasemos aqui.
    """
    if not autorizado(request):
        return JSONResponse({"error": "no autorizado"}, status_code=401)
    if accion not in ("arrancar", "parar", "reiniciar"):
        raise HTTPException(status_code=400, detail="accion invalida")
    import subprocess
    if accion == "parar":
        cmd = "systemctl stop hostapd"
    else:
        cmd = ("systemctl enable hostapd >/dev/null 2>&1; "
               "pkill -9 -x hostapd 2>/dev/null; "
               "ip link set %s down; sleep 2; ip link set %s up; sleep 2; "
               "systemctl restart hostapd" % (IFACE_AP, IFACE_AP))
    try:
        p = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL, start_new_session=True)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    return JSONResponse({"ok": True, "accion": accion, "pid": p.pid,
                         "ap": ap_estado()})


@app.get("/login")
async def login(request: Request):
    """Contrasena por query string (evita depender de python-multipart).

    Redirige a la pagina: si devuelve JSON, el navegador se queda viendo
    {"ok": true} en crudo en vez del monitor.

    Con el panel expuesto a internet hace falta frenar la fuerza bruta:
    se cuentan los fallos por IP y se bloquea un rato."""
    ip = request.client.host if request.client else "?"
    ahora = time.time()
    # limpieza de registros viejos
    for k in [k for k, v in _intentos.items() if ahora - v["t"] > INTENTOS_VENTANA]:
        _intentos.pop(k, None)
    reg = _intentos.get(ip)
    if reg and reg["n"] >= INTENTOS_MAX:
        return RedirectResponse("/?error=2", status_code=303)
    if TOKEN and request.query_params.get("pass") == TOKEN:
        _intentos.pop(ip, None)
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie("leelbox", TOKEN, httponly=True, samesite="lax",
                        max_age=60 * 60 * 24 * 30)
        return resp
    if reg and ahora - reg["t"] < INTENTOS_VENTANA:
        reg["n"] += 1
        reg["t"] = ahora
    else:
        _intentos[ip] = {"n": 1, "t": ahora}
    return RedirectResponse("/?error=1", status_code=303)


@app.get("/logout")
async def salir():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie("leelbox")
    return resp


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if TOKEN and not autorizado(request):
        return HTMLResponse(PAGINA_LOGIN)
    return HTMLResponse(PAGINA)


# ------------------------------------------------------------------ html

PAGINA_LOGIN = """<!doctype html><html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Leelbox</title><style>
body{background:#0d1117;color:#c9d1d9;font-family:system-ui,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
form{background:#161b22;padding:24px;border-radius:12px;width:260px}
input,button{width:100%;padding:10px;margin:6px 0;border-radius:6px;border:1px solid #30363d;
background:#0d1117;color:#c9d1d9;font-size:16px}
button{background:#238636;border-color:#2ea043;cursor:pointer}
 .mal{display:none;background:#3d1418;border:1px solid #f85149;color:#f85149;
 padding:9px;border-radius:6px;margin-bottom:10px;font-size:14px}
 .mal.on{display:block}
</style></head><body><form method="get" action="/login">
 <div class="mal" id="aviso">Contrasena incorrecta. Vuelve a escribirla.</div>
 <div class="mal" id="bloqueo">Demasiados intentos fallidos. Espera 15 minutos
 e intentalo de nuevo.</div>
 <h3>Leelbox</h3><input type="password" name="pass" placeholder="contraseña" autofocus>
 <button>Entrar</button>
 <div style="font-size:12px;color:#8b949e;margin-top:12px;line-height:1.5">
 Panel de la caja. La contrasena se guarda solo en este navegador
 (una por direccion: si cambias de IP tendras que entrar de nuevo).</div>
 </form>
 <script>
 (function(){
  var q=location.search||'';
  if(q.indexOf('error=2')>=0){
   var b=document.getElementById('bloqueo');
   if(b)b.className='mal on';
   var i=document.querySelector('input[name=pass]');
   if(i)i.disabled=true;
   var btn=document.querySelector('button');
   if(btn)btn.disabled=true;
  }else if(q.indexOf('error=1')>=0){
   var e=document.getElementById('aviso');
   if(e)e.className='mal on';
   var c=document.querySelector('input[name=pass]');
   if(c)c.focus();
  }
 })();
 </script></body></html>"""


PAGINA = """<!doctype html>
<html lang="es"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Leelbox Monitor</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#0d1117;color:#c9d1d9;
font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;font-size:15px}
header{position:sticky;top:0;z-index:5;background:#161b22;padding:10px 12px;
border-bottom:1px solid #30363d;display:flex;justify-content:space-between;align-items:center}
header b{color:#58a6ff}
main{padding:10px;max-width:900px;margin:0 auto}
h2{font-size:13px;text-transform:uppercase;color:#8b949e;margin:14px 4px 6px;
letter-spacing:.5px;font-weight:600}
.grid{display:grid;gap:8px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.card{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:10px}
.card .k{color:#8b949e;font-size:12px}
.card .v{font-size:19px;font-weight:600;margin-top:3px}
.bar{height:6px;background:#21262d;border-radius:3px;margin-top:7px;overflow:hidden}
.bar i{display:block;height:100%;background:#3fb950;border-radius:3px}
.ok{color:#3fb950}.warn{color:#d29922}.bad{color:#f85149}.dim{color:#8b949e}
.activo{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:12px;margin-bottom:8px}
.sim{font-weight:700;font-size:14px}
.precio{font-size:28px;font-weight:700;margin:4px 0;font-variant-numeric:tabular-nums}
.chg{font-size:14px;font-weight:600}
svg{display:block;width:100%;height:38px;margin-top:6px}
table{width:100%;border-collapse:collapse;font-size:13px}
td{padding:5px 2px;border-bottom:1px solid #21262d}
td:last-child{text-align:right;color:#8b949e}
.a{color:#3fb950}.b{color:#f85149}
footer{text-align:center;color:#484f58;font-size:12px;padding:14px}
a{color:#58a6ff}
</style></head><body>
<header><b>LEELBOX</b><span id="reloj" class="dim"></span></header>
<main>
<div id="caja"><h2>conectando...</h2></div>
<div id="aviso"></div>
</main>
<footer>actualiza solo cada 3 s &middot; <a href="/logout">salir</a></footer>
<script>
// Refresco automatico. Se pausa mientras el usuario tiene abierta la lista de
// redes, porque cada tick() reemplaza todo el HTML y la lista se perderia.
var redAbierta=false,timerTick=null;
function pausarTick(){if(timerTick){clearInterval(timerTick);timerTick=null;}}
function reanudarTick(){pausarTick();timerTick=setInterval(tick,3000);}

function barra(p){p=Math.max(0,Math.min(100,p||0));
return '<div class="bar"><i style="width:'+p+'%;background:'+
(p>90?'#f85149':p>75?'#d29922':'#3fb950')+'"></i></div>';}
function fmt(v,d){return (v===null||v===undefined)?'n/d':Number(v).toFixed(d);}
function spark(h){
 if(!h||h.length<2)return '';
 var W=300,H=38,lo=Math.min.apply(null,h),hi=Math.max.apply(null,h);
 if(hi-lo<1e-12)hi=lo+1e-9;
 var d='',i,x,y;
 for(i=0;i<h.length;i++){
  x=i/(h.length-1)*W; y=H-((h[i]-lo)/(hi-lo))*(H-4)-2;
  d+=(i?'L':'M')+x.toFixed(1)+' '+y.toFixed(1);
 }
 var ult=((h[h.length-1]-lo)/(hi-lo))*(H-4)+2;
 return '<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none">'+
 '<path d="'+d+'" fill="none" stroke="#58a6ff" stroke-width="1.6"/>'+
 '<circle cx="'+W+'" cy="'+ult.toFixed(1)+'" r="2.6" fill="#58a6ff"/></svg>';
}
function human(n){
 n=Number(n||0);var u=['B','KB','MB','GB','TB'],i=0;
 while(Math.abs(n)>=1024&&i<u.length-1){n/=1024;i++;}
 return n.toFixed(1)+' '+u[i];
}
function card(k,v,extra){return '<div class="card"><div class="k">'+k+
 '</div><div class="v">'+v+'</div>'+(extra||'')+'</div>';}

// Muestra el motivo real del fallo en vez de dejar "conectando" para siempre.
function mostrarAviso(txt){
 var c=document.getElementById('caja');
 if(c)c.innerHTML='<div class="card"><div class="bad">'+txt+'</div>'+
  '<div class="dim" style="font-size:12px;margin-top:8px">'+
  'Reintento automatico cada 3 segundos. Si sigue asi, revisa que la '+
  'contrasena sea correcta y que estes en la red Leelbox.</div></div>';
}

if((location.search||'').indexOf('error=1')>=0){
 var av=document.getElementById('aviso');
 if(av)av.innerHTML=
  '<div class="activo" style="border-color:#f85149;color:#f85149">'+
  'Contrasena incorrecta</div>';
}
async function tick(){
 try{
  if(redAbierta)return;
  // Con limite de tiempo: si la peticion se queda colgada, el panel no
  // puede quedarse eternamente en "conectando".
  var ctrl=new AbortController();
  var to=setTimeout(function(){ctrl.abort();},12000);
  var r;
  try{
   r=await fetch('/api/estado',{cache:'no-store',signal:ctrl.signal});
  }finally{clearTimeout(to);}
  if(r.status===401){location.href='/';return;}
  if(r.status!==200){
   mostrarAviso('La caja respondio '+r.status+'. Reintentando...');
   return;
  }
  var d=await r.json();var s=d.sistema,t=d.trading;
  if(!s||!t){mostrarAviso('Respuesta incompleta de la caja.');return;}
  var h='';

  h+='<h2>Activos</h2>';
  if(!t.ok){
   h+='<div class="activo"><div class="bad">'+t.error+'</div></div>';
  }else{
   (t.activos||[]).forEach(function(a){
    var c=a.variacion>0?'a':(a.variacion<0?'b':'dim');
    var viv=a.conectado&&a.corriendo&&a.tick_reciente;
    var estado=viv?'EN VIVO':(a.conectado&&a.corriendo?'SIN DATOS':'PARADO');
    h+='<div class="activo">';
    h+='<div style="display:flex;justify-content:space-between">'+
       '<span class="sim">'+a.simbolo+'</span>'+
       '<span class="'+(viv?'ok':(a.conectado&&a.corriendo?'dim':'bad'))+'">'+estado+'</span></div>';
    h+='<div class="precio">'+fmt(a.precio,a.decimales)+'</div>';
    h+='<div class="chg '+c+'">'+(a.variacion===null?'':
       (a.variacion>0?'▲ ':a.variacion<0?'▼ ':'')+
       (a.variacion>0?'+':'')+fmt(a.variacion,a.decimales)+
       '  ('+(a.var_pct>0?'+':'')+fmt(a.var_pct,3)+'%)')+'</div>';
    h+=spark(a.hist);
    h+='<table style="margin-top:8px">'+
       '<tr><td>minimo</td><td>'+fmt(a.min,a.decimales)+'</td></tr>'+
       '<tr><td>maximo</td><td>'+fmt(a.max,a.decimales)+'</td></tr>'+
       '<tr><td>velas en bufer</td><td>'+a.velas+'</td></tr>'+
       '<tr><td>senales</td><td>'+a.senales+'</td></tr>'+
       (a.error?'<tr><td>error</td><td class="bad">'+a.error+'</td></tr>':'')+
       '</table></div>';
   });
  }

  h+='<h2>Deriv</h2><div class="grid">';
  h+=card('conexion',t.ok?(t.conectado?'<span class="ok">conectado</span>':
      '<span class="bad">desconectado</span>'):'<span class="bad">sin API</span>');
  h+=card('latencia',t.latencia?Math.round(t.latencia)+' ms':'n/d');
  h+=card('estado / version',(t.estado||'n/d')+' &middot; v'+(t.version||'?'));
  h+=card('estrategias',t.estrategias===undefined?'n/d':t.estrategias);
  h+='</div>';

  h+='<h2>Sistema</h2><div class="grid">';
  h+=card('CPU',(s.cpu===null?'n/d':s.cpu.toFixed(0)+' %')+
      '<div class="dim" style="font-size:12px">'+s.nucleos+' nucleos &middot; load '+
      s.load.map(function(x){return x.toFixed(2);}).join(' ')+'</div>'+barra(s.cpu));
  h+=card('Memoria',human(s.mem.usada)+' / '+human(s.mem.total),
      '<div class="dim" style="font-size:12px">libre '+human(s.mem.disp)+'</div>'+
      barra(100*s.mem.usada/s.mem.total));
  h+=card('Disco',human(s.disco.usada)+' / '+human(s.disco.total),
      '<div class="dim" style="font-size:12px">'+s.carga_disco+'</div>'+
      barra(100*s.disco.usada/s.disco.total));
  h+=card('Temperatura',s.temp?s.temp.toFixed(0)+' °C':'n/d',
      '<div class="dim" style="font-size:12px">limite 90 °C</div>'+
      (s.temp?barra(100*s.temp/105):''));
  h+=card('Red',s.ssid+'<div class="dim" style="font-size:12px">'+s.ip+
      ' &middot; '+(s.senal===null?'n/d':s.senal+' dBm')+'</div>');
  h+=card('Uptime',human(s.uptime));
  h+='</div>';

  // ---------------- AP propio (RT3070)
  var a=d.ap||{};
  var et=function(ok,txt){return ok?'<span class="ok"> &middot; '+txt+'</span>'
                                      :'<span class="bad"> &middot; '+txt+'</span>';};
  h+='<h2>Punto de acceso propio</h2><div class="grid">';
  h+=card('estado',(a.activo?'Leelbox encendida':'Leelbox apagada')+
     (a.arrancando?et(0,'arrancando'):et(a.activo&&a.estado==='ENABLED',
                                         a.estado||'sin estado')));
  h+=card('ssid / canal',(a.ssid||'Leelbox')+' &middot; canal '+
     (a.canal||'6'));
  h+=card('clientes',a.clientes||0);
  h+=card('direccion',a.ip||'192.168.50.1');
  h+='</div>';

  h+='<div class="card"><button id="bnap" style="width:100%;padding:12px;'+
     'font-size:15px">'+(a.activo?'Reiniciar AP':'Encender AP')+
     '</button><div class="dim" style="font-size:12px;margin-top:8px">'+
     'Desde el celular conectate a esta red y entra a '+
     '<b>http://'+(a.ip||'192.168.50.1')+':8080</b> para llegar a la '+
     'caja sin internet.</div></div>';

  // ---------------- elegir red de internet
  var w=d.wifi||{};
  h+='<h2>Red de internet</h2><div class="grid">';
  h+=card('red actual',w.ssid||'sin red')+
     (w.conectado?et(1,'conectado'):et(0,'desconectado'));
  h+=card('ip de la caja',w.ip||'sin IP');
  h+=card('senal',w.senal===null?'n/d':w.senal+' dBm');
  h+='</div>';
  h+='<div class="card"><button id="bnet" style="width:100%;padding:12px;'+
     'font-size:15px">Buscar redes y cambiar</button>'+
     '<div id="zredes"></div></div>';
  if((t.senales||[]).length){
   h+='<h2>Senales</h2><div class="card"><table>';
   t.senales.forEach(function(x){
    h+='<tr><td>'+x.etiqueta+'</td><td>'+x.valor+'</td></tr>';});
   h+='</table></div>';
  }

  document.getElementById('caja').innerHTML=h;

  // Los botones se enganchan DESPUES de inyectar el HTML: si se buscan
  // antes, el elemento aun no existe y el clic no hace nada.
  var botonAp=document.getElementById('bnap');
  if(botonAp)botonAp.onclick=function(){
   var acc=a.activo?'reiniciar':'arrancar';
   // OJO: dentro de PAGINA los saltos de linea en literales de JS deben
   // escribirse con dos barras invertidas, porque Python convierte un
   // escape simple en un salto real y el script deja de parsear.
   if(!confirm(a.activo?
    'Reiniciar el AP "Leelbox"?\\n\\nSi estas conectado por esa red, la conexion se cae unos 12 segundos y hay que volver a entrar.':
    'Encender el AP "Leelbox"?'))return;
   botonAp.disabled=true;botonAp.textContent='un momento...';
   fetch('/api/ap/'+acc,{method:'POST'})
    .then(function(){setTimeout(function(){tick();},3000);})
    .catch(function(e){botonAp.textContent='fallo: '+e;})
    .finally(function(){botonAp.disabled=false;});
  };

  var botonNet=document.getElementById('bnet');
  if(botonNet)botonNet.onclick=function(){
   botonNet.disabled=true;botonNet.textContent='buscando redes...';
   var z=document.getElementById('zredes');
   //Mientras la lista esta abierta se pausa el refresco automatico: si no,
   // el tick() de 3 segundos repondria el HTML y la lista desapareceria.
   redAbierta=true;pausarTick();
   z.innerHTML='<div class="dim">Escaneando, puede tardar 10 segundos...</div>';
   fetch('/api/wifi/redes').then(function(r){return r.json();})
    .then(function(j){
     var rs=(j.redes||[]);
     if(!rs.length){z.innerHTML='<div class="bad">No se encontraron redes.'+
      '<br><button id="cerrarL" style="margin-top:9px;padding:8px 12px">'+
      'Cerrar</button></div>';cerrar();return;}
     z.innerHTML='<div style="margin-top:10px">'+
      '<div class="dim" style="margin-bottom:6px">'+
      '<button id="cerrarL" style="padding:6px 11px">Cerrar lista</button>'+
      '<button id="reScan" style="padding:6px 11px;margin-left:7px">'+
      'Escanear otra vez</button></div>'+
      rs.map(function(r){
       var fuerte=r.senal!==null?r.senal+' dBm':'n/d';
       var tag='<span class="dim">2.4 GHz</span>';
       if(r.freq>4000&&r.freq<5900)tag='<span class="dim">5 GHz</span>';
       return '<div style="border-top:1px solid #333;padding:9px 0">'+
        '<div style="display:flex;justify-content:space-between">'+
        '<b>'+(r.ssid||'(oculta)')+'</b><span class="dim">'+fuerte+'</span></div>'+
        '<div class="dim" style="font-size:12px">'+tag+
        (r.seguro?' &middot; con clave':' &middot; abierta')+
        (r.conocida?' &middot; ya guardada':'')+'</div>'+
        '<button data-ssid="'+r.ssid.replace(/"/g,'')+'" '+
        'style="margin-top:7px;padding:8px 12px">Conectarse</button></div>';
      }).join('')+'</div>';
     z.querySelectorAll('button[data-ssid]').forEach(function(b){
      b.onclick=function(){conectarRed(b.getAttribute('data-ssid'),z,b);};
     });
     document.getElementById('cerrarL').onclick=cerrar;
     document.getElementById('reScan').onclick=function(){
      var b=document.getElementById('bnet');if(b)b.onclick();};
    })
    .catch(function(){z.innerHTML='<div class="bad">Fallo al escanear.'+
     '<br><button id="cerrarL" style="margin-top:9px;padding:8px 12px">'+
     'Cerrar</button></div>';cerrar();});
   };


  var n=new Date();document.getElementById('reloj').textContent=
   n.toTimeString().slice(0,8);
 }catch(e){mostrarAviso('Error leyendo la caja: '+
   (e&&e.message?e.message:e));}
}

function conectarRed(ssid,z,boton){
 var clave=prompt('Clave de la red "'+ssid+'" (dejala vacia si es abierta):');
 if(clave===null)return;
 boton.disabled=true;boton.textContent='conectando...';
 z.innerHTML='<div class="dim">Conectando a '+ssid+'...</div>';
 fetch('/api/wifi/conectar',{method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({ssid:ssid,clave:clave})})
  .then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})
  .then(function(res){
   if(res.ok){z.innerHTML='<div class="ok">Conectado a '+ssid+'.</div>'+
    '<br><button id="cerrarL" style="margin-top:9px;padding:8px 12px">'+
    'Listo, cerrar</button>';
    document.getElementById('cerrarL').onclick=cerrar;
    redAbierta=false;reanudarTick();}
   else{z.innerHTML='<div class="bad">'+
     (res.j.error||'no se pudo conectar')+'</div>';
    boton.disabled=false;boton.textContent='Reintentar';}
  })
  .catch(function(){z.innerHTML='<div class="bad">Fallo la peticion.</div>';
   boton.disabled=false;boton.textContent='Reintentar';});
}

function cerrar(){redAbierta=false;reanudarTick();}

tick();reanudarTick();
</script></body></html>"""

def _socket(host, familia, v6only=False):
    """Socket listo para escuchar. En IPv6 se fuerza IPV6_V6ONLY para que no
    choque con el socket IPv4 del mismo puerto."""
    import socket
    s = socket.socket(familia, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if v6only and familia == socket.AF_INET6:
        s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    s.bind((host, PUERTO))
    s.listen(128)
    s.set_inheritable(True)
    return s


def _servir():
    """Escucha en IPv4 (obligatorio para la red local) y en IPv6 (para que
    'localhost', que resuelve primero a ::1, no falle)."""
    import socket
    import threading

    import uvicorn

    nivel = os.environ.get("LEELBOX_MONITOR_LOG", "warning")

    def _correr(sock, etiqueta):
        cfg = uvicorn.Config(app, log_level=nivel, access_log=False)
        uvicorn.Server(cfg).run(sockets=[sock])
        print("monitor: escucha %s detenida" % etiqueta)

    # IPv4: red local y celu
    s4 = _socket("0.0.0.0", socket.AF_INET)
    hilos = []

    if socket.has_ipv6:
        try:
            s6 = _socket("::1", socket.AF_INET6, v6only=True)
            h = threading.Thread(target=_correr, args=(s6, "IPv6 ::1"),
                                 daemon=True)
            h.start()
            hilos.append(h)
            print("monitor: escuchando en [::1]:%d (IPv6, para localhost)"
                  % PUERTO)
        except OSError as e:
            print("monitor: sin IPv6 (%s)" % e)

    print("monitor: escuchando en 0.0.0.0:%d (IPv4, red local)" % PUERTO)
    _correr(s4, "IPv4 0.0.0.0")


if __name__ == "__main__":
    _servir()
