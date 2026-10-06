#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Alertas: NTFY, cola, deduplicación, cooldown."""
import base64
import hashlib
import logging
import os
import re
import math
import requests
from datetime import datetime, timezone
from typing import List
from core.estructuras import Signal, AlertEntry

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class AlertasEngine:
    def __init__(self, ntfy_topic: str = "", ntfy_server: str = "https://ntfy.sh",
                 symbol: str = "", point: float = 0.00001):
        self.ntfy_topic = ntfy_topic
        self.ntfy_server = ntfy_server.rstrip("/")
        self.symbol = symbol
        self.point = point
        self.g_last_alert_time = _now_utc()
        self.g_last_ntfy_time = _now_utc().replace(microsecond=0)  # epoch aware
        self.g_alert_queue: List[AlertEntry] = []
        self.MAX_ALERT_QUEUE = 50

    def _fmt_price(self, value: float) -> str:
        digits = max(0, int(round(-math.log10(self.point)))) if self.point > 0 else 5
        return f"{value:.{digits}f}"

    def build_alert_text(self, sig: Signal) -> str:
        dir_text = "CALL" if sig.direction == 1 else "PUT"
        dir_emoji = "🟢" if sig.direction == 1 else "🔴"
        sep = "━━━━━━━━━━━━━━━━━━━━"
        msg = sep + "\n"
        msg += f"{dir_emoji} {dir_text} — {sig.symbol} — {sig.detector}"
        if sig.tipo:
            msg += f" · {sig.tipo}"
        msg += "\n" + sep + "\n"
        et = sig.entry_time
        hora = f"{et.hour:02d}:{et.minute:02d}" if et else "00:00"
        msg += f"⚡ {hora} {sig.session}"
        if sig.kill_zone != "NONE":
            msg += f" · {sig.kill_zone}"
        msg += "\n" + sep + "\n"

        msg += "🔮 HIPÓTESIS\n" + sep + "\n"
        msg += sig.hipotesis_causa + "\n"
        msg += sig.hipotesis_efecto + "\n"
        msg += sig.hipotesis_razon + "\n"
        msg += sig.hipotesis_invalidez + "\n" + sep + "\n"

        confirms = ""
        if sig.detector == "D1":
            if sig.br > 0.70: confirms += "Cuerpo fuerte · "
            if sig.bs > 0.80: confirms += "Penetración profunda · "
            if sig.kill_zone != "NONE": confirms += "Kill Zone · "
        elif sig.detector in ("D2", "D2_ANTICIPACION"):
            if sig.equal_hl_detected: confirms += "Nivel igual · "
            if sig.hipotesis_zona != "NEUTRO": confirms += sig.hipotesis_zona + " · "
            if sig.sweep_volume_ratio > 1.5: confirms += "Volumen alto · "
            if sig.kill_zone != "NONE": confirms += "Kill Zone · "
            if sig.displacement_post_sweep: confirms += "Displacement ✓ · "
            if sig.toques_nivel >= 3: confirms += f"{sig.toques_nivel} toques · "
        elif sig.detector in ("D3", "D3_DEF"):
            if sig.detector == "D3_DEF": confirms += "FVG defendido · "
            if sig.hipotesis_zona != "NEUTRO": confirms += sig.hipotesis_zona + " · "
            if sig.mss_aligned: confirms += "MSS H4 · "
            if sig.kill_zone != "NONE": confirms += "Kill Zone · "
        elif sig.detector == "D4":
            if sig.ob_impulse_atr > 1.5: confirms += "Impulso fuerte · "
            if sig.kill_zone != "NONE": confirms += "Kill Zone · "
        elif sig.detector == "D5":
            confirms += f"MSS H4 {sig.mss_direction} · "
            if sig.kill_zone != "NONE": confirms += "Kill Zone · "
            if sig.displacement_post_sweep: confirms += "Displacement ✓ · "

        if len(confirms) > 2:
            confirms = confirms[:-3]
        msg += "✅ CONFIRMACIONES\n" + sep + "\n" + confirms + "\n" + sep + "\n"

        msg += "🔍 DIAGNÓSTICO\n" + sep + "\n"
        if sig.velocidad_aproximacion >= 70:
            vel_txt = "RÁPIDA"
        elif sig.velocidad_aproximacion >= 50:
            vel_txt = "NORMAL"
        else:
            vel_txt = "LENTA"
        msg += f"⚡ Velocidad aprox: {vel_txt} ({sig.velocidad_aproximacion:.0f}/100)\n"
        msg += f"🌊 Régimen: {sig.regimen_volatilidad}\n"
        msg += sep + "\n"

        msg += f"⏱️ VENCIMIENTO: {sig.hipotesis_expiry_velas} vela(s) M15 ({sig.hipotesis_expiry_minutos} min)\n" + sep + "\n"
        msg += f"💰 REFERENCIA: {self._fmt_price(sig.entry_price)} | Objetivo: {self._fmt_price(sig.hipotesis_objetivo)}\n" + sep + "\n"
        msg += f"📊 PROBABILIDAD: {sig.hipotesis_prob_min}-{sig.hipotesis_prob_max}%\n"
        conv_emoji = {"ALTA": "🔥", "MEDIA": "⚡", "BAJA": "💤"}.get(sig.conviccion, "⚡")
        msg += f"{conv_emoji} CONVICCIÓN: {sig.conviccion}\n" + sep + "\n"
        msg += "📍 Dato para evaluar, no una orden."
        return msg

    # ---------- presentacion de las alertas ntfy -------------------------
    # URL del monitor web: las notificaciones abren con un toque.
    MONITOR_URL = os.environ.get("LEELBOX_MONITOR_URL",
                                 "http://10.0.0.34:8080").rstrip("/")

    _RE_DIR = re.compile(r"(\U0001F7E2|\U0001F534)\s*(CALL|PUT)\s*\u2014\s*([A-Z0-9]+)(?:\s*\u2014\s*([A-Za-z0-9_]+))?")
    _RE_CONV = re.compile(r"CONVICCI\u00d3N:\s*(\w+)")
    _RE_PROB = re.compile(r"PROBABILIDAD:\s*(\d+)\s*-\s*(\d+)\s*%")
    _RE_HORA = re.compile(r"\u26a1\s*(\d{2}:\d{2})\s*(\w*)")
    _RE_SEP = re.compile(r"^[\u2501\u2500\s]{4,}$", re.M)
    _RE_CAB = re.compile(r"^\u26a1\s*(\d{2}:\d{2})\s*(\w*)\s*"
                        r"(?:\u00b7\s*([A-Z_]+))?\s*$")
    _RE_SECCION = re.compile(
        r"^(?:(\U0001F52E|\u2705|\U0001F50D|\U0001F4CA|\U0001F4B0|\u23f1\ufe0f|\U0001F4CD)"
        r"\s*)?([A-Z\u00c1\u00c9\u00cd\u00d3\u00da\u00d1][A-Z\u00c1\u00c9\u00cd\u00d3\u00da\u00d1 ]{3,})"
        r"[:\s]*$", re.M)

    def _meta_alerta(self, text: str) -> dict:
        """Datos de la alerta que van en las cabeceras de ntfy."""
        m = self._RE_DIR.search(text)
        meta = {
            "direccion": m.group(2) if m else "",
            "simbolo": m.group(3) if m else "",
            "detector": (m.group(4) or "") if m else "",
            "conviccion": "",
            "prob_min": 0,
            "prob_max": 0,
            "hora": "",
            "sesion": "",
        }
        c = self._RE_CONV.search(text)
        if c:
            meta["conviccion"] = c.group(1)
        p = self._RE_PROB.search(text)
        if p:
            meta["prob_min"] = int(p.group(1))
            meta["prob_max"] = int(p.group(2))
        h = self._RE_HORA.search(text)
        if h:
            meta["hora"] = h.group(1)
            meta["sesion"] = h.group(2) or ""
        return meta

    _SECCIONES = {
        "HIP\u00d3TESIS": "Hip\u00f3tesis",
        "CONFIRMACIONES": "Confirmaciones",
        "DIAGN\u00d3STICO": "Diagn\u00f3stico",
    }
    _RE_SEC = re.compile(
        r"^(\U0001F52E|\u2705|\U0001F50D)?\s*"
        r"(HIP\u00d3TESIS|CONFIRMACIONES|DIAGN\u00d3STICO)\s*[:\s]*$")
    # etiquetas sueltas -> "**Etiqueta:** valor"
    _ETIQUETAS = [
        (re.compile(r"^\S*\s*Velocidad aprox:\s*(.*)$"), "Velocidad"),
        (re.compile(r"^\S*\s*R[e\u00e9]gimen:\s*(.*)$"), "R\u00e9gimen"),
        (re.compile(r"^\S*\s*VENCIMIENTO:\s*(.*)$"), "Vence"),
        (re.compile(r"^\S*\s*REFERENCIA:\s*(.*)$"), "Referencia"),
        (re.compile(r"^\S*\s*PROBABILIDAD:\s*(.*)$"), "Probabilidad"),
        (re.compile(r"^\S*\s*CONVICCI\u00d3N:\s*(.*)$"), "Convicci\u00f3n"),
    ]

    _SECCIONES = {
        "HIP\u00d3TESIS": "Hip\u00f3tesis",
        "CONFIRMACIONES": "Confirmaciones",
        "DIAGN\u00d3STICO": "Diagn\u00f3stico",
    }
    _RE_SEC = re.compile(
        r"^(\U0001F52E|\u2705|\U0001F50D)?\s*"
        r"(HIP\u00d3TESIS|CONFIRMACIONES|DIAGN\u00d3STICO)\s*[:\s]*$")
    _ETIQUETAS = [
        (re.compile(r"^\S*\s*Velocidad aprox:\s*(.*)$"), "Velocidad"),
        (re.compile(r"^\S*\s*R[e\u00e9]gimen:\s*(.*)$"), "R\u00e9gimen"),
        (re.compile(r"^\S*\s*VENCIMIENTO:\s*(.*)$"), "Vence"),
        (re.compile(r"^\S*\s*REFERENCIA:\s*(.*)$"), "Referencia"),
        (re.compile(r"^\S*\s*PROBABILIDAD:\s*(.*)$"), "Probabilidad"),
        (re.compile(r"^\S*\s*CONVICCI\u00d3N:\s*(.*)$"), "Convicci\u00f3n"),
    ]

    def _cuerpo_markdown(self, text: str) -> str:
        """Cuerpo compacto, pensado para que entre entero en la pantalla del
        celular: sin separadores, sin punto colgante, un solo renglón de aire
        por seccion y los parrafos continuos unidos en un solo bloque para que
        el texto fluya y ocupe el ancho disponible en vez de dejar renglones
        cortos."""
        out = []
        seccion = ""          # seccion en curso

        def _aire():
            if out and out[-1] != "":
                out.append("")

        def _es_dato(linea):
            """True si la linea ya es una etiqueta en negrita."""
            return linea.startswith("**")

        for bruta in text.splitlines():
            l = bruta.strip()
            if not l or set(l) <= set("\u2501\u2500 "):
                continue
            # La primera linea repite direccion y simbolo, que
            # ntfy ya muestra en el Title: se descarta para no
            # gastar un renglon del celular en lo mismo.
            if self._RE_DIR.match(l):
                continue

            # Cabecera "⚡ 09:47 ASIA · KILL_ZONE": ntfy ya pone la hora en
            # la notificacion, asi que se saca del cuerpo y la sesion pasa al
            # diagnostico. El encabezado queda en una sola linea (el Title).
            cab = self._RE_CAB.match(l)
            if cab and not seccion:
                sesion = (cab.group(2) or "").strip()
                kill = (cab.group(3) or "").strip()
                extra = " \u00b7 ".join(x for x in (sesion, kill) if x)
                if extra:
                    self._contexto = extra
                continue

            m = self._RE_SEC.match(l)
            if m:
                etq, clave = m.group(1) or "", m.group(2)
                seccion = self._SECCIONES[clave]
                _aire()
                out.append("**%s %s**" % (etq, seccion))
                out.append("")
                if seccion == "Diagn\u00f3stico" and getattr(self, "_contexto", ""):
                    out.append("**Sesi\u00f3n:** %s" % self._contexto)
                continue

            l = re.sub(r"[\u00b7\s]+$", "", l)
            for rx, nombre in self._ETIQUETAS:
                mm = rx.match(l)
                if mm:
                    l = "**%s:** %s" % (nombre, mm.group(1).strip())
                    break
            l = re.sub(r"\|\s*Objetivo:?\s*", " \u2192 **Objetivo:** ", l)
            l = re.sub(r"  +", " ", l).strip()
            if not l:
                continue

            # La hipotesis son varias frasesfollowed: se unen en un parrafo
            # para que el celular las envuelva y aproveche el ancho.
            if (seccion == "Hip\u00f3tesis" and out and out[-1] != ""
                    and not _es_dato(out[-1]) and not _es_dato(l)):
                out[-1] = out[-1] + " " + l
                continue

            out.append(l)

        while out and out[-1] == "":
            out.pop()
        return "\n".join(out)

    def _cabeceras_ntfy(self, meta: dict) -> dict:
        """Titulo, prioridad, iconos y boton al monitor, ya codificados."""
        # Titulo solo ASCII: requests envia las cabeceras en latin-1 y ntfy
        # las URL-encoda, con lo cual el movil puede mostrarlas con %25F0...
        # Los iconos llegan igual por los Tags, que ntfy traduce a emoji.
        conv = (meta.get("conviccion") or "").upper()
        bits = [b for b in (meta.get("direccion"), meta.get("simbolo")) if b]
        titulo = " - ".join(bits) if bits else "PIVOT"
        if meta.get("detector"):
            titulo += " - %s" % meta["detector"]
        if conv:
            titulo += " - %s" % conv

        prob = meta.get("prob_max") or 0
        if conv == "ALTA" and prob >= 80:
            prio = "high"
        elif conv == "BAJA":
            prio = "default"
        else:
            prio = "default"

        tags = ["chart_with_upwards_trend" if meta.get("direccion") == "CALL"
                else "chart_with_downwards_trend"]
        if conv == "ALTA":
            tags.append("fire")
        if conv == "BAJA":
            tags.append("zzz")

        # La URL de silenciado necesita esquema o ntfy descarta la accion.
        silencio = "%s/%s" % (self.ntfy_server, self.ntfy_topic)

        cabeceras = {
            "Title": titulo,
            "Priority": prio,
            "Tags": ",".join(tags),
            "Click": self.MONITOR_URL,
            # Sin codificar: ntfy necesita los separadores "action=" y ";".
            "Actions": ("action=view, Abrir monitor, %s; "
                        "action=http, Silenciar, %s"
                        % (self.MONITOR_URL, silencio)),
            "Markdown": "yes",
            "Content-Type": "text/markdown; charset=utf-8",
        }
        # Servidor ntfy propio: exige credenciales. Se leen del entorno
        # para no pasarlas por todos los llamadores.
        _usr = os.environ.get("NTFY_USER", "")
        _psw = os.environ.get("NTFY_PASS", "")
        if _usr and _psw:
            _tok = base64.b64encode(
                ("%s:%s" % (_usr, _psw)).encode()).decode()
            cabeceras["Authorization"] = "Basic " + _tok
        return cabeceras

    def send_ntfy_message(self, text: str, *, forzar: bool = False) -> bool:
        if not self.ntfy_topic:
            return False
        # Gate global: en prueba/replay no se spamea ntfy live.
        if not forzar:
            from kernel.ntfy import alertas_live_habilitadas
            if not alertas_live_habilitadas():
                return False
        if (datetime.now(timezone.utc) - self.g_last_ntfy_time).total_seconds() < 5:
            return False
        url = f"{self.ntfy_server}/{self.ntfy_topic}"
        meta = self._meta_alerta(text)
        headers = self._cabeceras_ntfy(meta)
        cuerpo = self._cuerpo_markdown(text)
        try:
            resp = requests.post(url, data=cuerpo.encode("utf-8"),
                                 headers=headers, timeout=3)
            if resp.status_code in (200, 201):
                self.g_last_ntfy_time = datetime.now(timezone.utc)
                return True
            logger.warning(f"ntfy HTTP {resp.status_code} para topic {self.ntfy_topic}")
            return False
        except Exception as e:
            logger.error(f"Error enviando ntfy: {e}")
            return False

    def queue_alert(self, text: str):
        if len(self.g_alert_queue) >= self.MAX_ALERT_QUEUE:
            self.g_alert_queue.pop(0)
        hash_val = hashlib.md5(text.encode("utf-8")).hexdigest()
        for a in self.g_alert_queue:
            if a.content_hash == hash_val:
                return
        entry = AlertEntry()
        entry.text = text
        entry.content_hash = hash_val
        entry.retry_count = 0
        entry.last_retry = datetime(1970, 1, 1, tzinfo=timezone.utc)
        entry.created_at = datetime.now(timezone.utc)
        self.g_alert_queue.append(entry)

    def process_alert_queue(self):
        if not self.g_alert_queue:
            return
        now = datetime.now(timezone.utc)
        keep = []
        for alert in self.g_alert_queue:
            backoff = (2 ** min(alert.retry_count, 6)) * 5
            if alert.retry_count > 0 and (now - alert.last_retry).total_seconds() < backoff:
                keep.append(alert)
                continue
            if self.send_ntfy_message(alert.text):
                logger.info("Alerta encolada enviada")
            else:
                alert.retry_count += 1
                alert.last_retry = now
                if alert.retry_count >= 3:
                    logger.error(f"Alerta descartada tras {alert.retry_count} reintentos: {alert.text[:80]}")
                else:
                    keep.append(alert)
        self.g_alert_queue = keep

    def flush_alert_queue(self):
        max_flush = min(len(self.g_alert_queue), 3)
        sent_indices = []
        for i in range(max_flush):
            if self.send_ntfy_message(self.g_alert_queue[i].text):
                sent_indices.append(i)
        for i in sorted(sent_indices, reverse=True):
            self.g_alert_queue.pop(i)
