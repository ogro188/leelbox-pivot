#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Collector read-only de precios OTC de IQ Option (GraphQL público).

Fase 1 del plan de integración:
- No requiere login, API key, cookie ni SSID.
- No arranca el motor PIVOT, no genera señales y no toca activos/ ni el runtime.
- Guarda ticks y construye velas M1/M15 en una SQLite separada.
- Envía alertas de salud a ntfy con un topic propio (no usa los topics reales).
- Exporta CSV con el formato que consume el backtest de PIVOT.

Uso:
    python scripts/iq_public_collector.py --once
    python scripts/iq_public_collector.py --loop
    python scripts/iq_public_collector.py --status
    python scripts/iq_public_collector.py --quality
    python scripts/iq_public_collector.py --export
    python scripts/iq_public_collector.py --ntfy-test

Variables de entorno:
    IQ_PUBLIC_ACTIVE_IDS      IDs separados por coma (default: 76,1857)
    IQ_PUBLIC_INTERVAL        Segundos entre consultas (default: 1.0)
    IQ_PUBLIC_DB              Ruta de la SQLite (default: data/iq_public/iq_public.db)
    IQ_PUBLIC_EXPORT_DIR      Directorio de exportación
    IQ_PUBLIC_NTFY_TOPIC      Topic de salud (default: pivot_EJEMPLO_OTC_health)
    IQ_PUBLIC_NTFY_SERVER     Servidor ntfy (default: https://ntfy.sh)
    IQ_PUBLIC_NTFY_USER       Usuario ntfy (fallback: NTFY_USER)
    IQ_PUBLIC_NTFY_PASS       Password ntfy (fallback: NTFY_PASS)
    IQ_PUBLIC_STALE_AFTER     Segundos sin datos para alertar (default: 60)
    IQ_PUBLIC_KEEP_TICKS_DAYS Días de ticks crudos a conservar (default: 14; 0 = infinito)
    IQ_PUBLIC_CHART_REFRESH   Segundos entre refrescos de charts.d1 (default: 600)
"""
from __future__ import annotations

import argparse
import base64
import csv
import fcntl
import json
import logging
import os
import signal
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kernel.feeds.iqoption_public import (
    Bar,
    BarBuilder,
    IQActiveQuote,
    IQChart,
    IQPublicClient,
    IQPublicError,
)

LOGGER = logging.getLogger("iq-otc-collector")

DEFAULT_IDS = "76,1857"
DEFAULT_INTERVAL = 1.0
DEFAULT_STALE_AFTER = 60.0
DEFAULT_HEALTH_EVERY = 60.0
DEFAULT_KEEP_TICKS_DAYS = 14.0
DEFAULT_CHART_REFRESH = 600.0
DEFAULT_CHART_PERIOD = "d1"
DEFAULT_NTFY_TOPIC = "pivot_EJEMPLO_OTC_health"
DEFAULT_NTFY_SERVER = "https://ntfy.sh"
DEFAULT_DB = ROOT / "data" / "iq_public" / "iq_public.db"
DEFAULT_EXPORT_DIR = ROOT / "data" / "iq_public" / "export"


SCHEMA = """
CREATE TABLE IF NOT EXISTS ticks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    active_id INTEGER NOT NULL,
    provider_name TEXT NOT NULL,
    ticker TEXT,
    is_otc INTEGER NOT NULL DEFAULT 1,
    ts REAL NOT NULL,
    price REAL NOT NULL,
    bid REAL,
    ask REAL,
    payout_turbo_pct REAL,
    payout_binary_pct REAL,
    session_open REAL,
    session_close REAL,
    latency_ms REAL,
    ts_source TEXT NOT NULL DEFAULT 'local_receive'
);
CREATE INDEX IF NOT EXISTS idx_ticks_active_ts ON ticks(active_id, ts);
CREATE INDEX IF NOT EXISTS idx_ticks_ts ON ticks(ts);

CREATE TABLE IF NOT EXISTS bars (
    active_id INTEGER NOT NULL,
    provider_name TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    open_time INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    bid_open REAL,
    bid_close REAL,
    ask_open REAL,
    ask_close REAL,
    ticks INTEGER NOT NULL,
    first_tick_ts REAL,
    last_tick_ts REAL,
    PRIMARY KEY (active_id, timeframe, open_time)
);
CREATE INDEX IF NOT EXISTS idx_bars_provider_tf_time
    ON bars(provider_name, timeframe, open_time);

CREATE TABLE IF NOT EXISTS chart_quotes (
    active_id INTEGER NOT NULL,
    provider_name TEXT NOT NULL,
    period TEXT NOT NULL,
    ts INTEGER NOT NULL,
    price REAL NOT NULL,
    fetched_at REAL NOT NULL,
    PRIMARY KEY (active_id, period, ts)
);
CREATE INDEX IF NOT EXISTS idx_chart_provider_period_ts
    ON chart_quotes(provider_name, period, ts);

CREATE TABLE IF NOT EXISTS collector_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    status TEXT NOT NULL,
    last_tick_age_s REAL,
    latency_ms REAL,
    requests_total INTEGER NOT NULL,
    errors_total INTEGER NOT NULL,
    consecutive_errors INTEGER NOT NULL,
    ticks_total INTEGER NOT NULL,
    bars_m1_total INTEGER NOT NULL,
    bars_m15_total INTEGER NOT NULL,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_health_ts ON collector_health(ts);
"""


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path


def parse_ids(raw: str) -> List[int]:
    ids: List[int] = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError as exc:
            raise ValueError(f"ID inválido: {part!r}") from exc
        if value <= 0:
            raise ValueError(f"ID inválido: {part!r}")
        if value not in ids:
            ids.append(value)
    if not ids:
        raise ValueError("No hay IDs configurados")
    return ids


def iso_utc(timestamp: float) -> str:
    return datetime.fromtimestamp(float(timestamp), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def csv_ts(open_time: int) -> str:
    return datetime.fromtimestamp(int(open_time), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def db_size_bytes(path: Path) -> int:
    total = 0
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            try:
                total += candidate.stat().st_size
            except OSError:
                pass
    return total


def connect_db(path: Path, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        if not path.exists():
            raise FileNotFoundError(path)
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=15)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=15)
        conn.execute("PRAGMA journal_mode=WAL").fetchone()
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=10000")
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------

@dataclass
class RuntimeStats:
    started_at: float = field(default_factory=time.time)
    requests_total: int = 0
    errors_total: int = 0
    consecutive_errors: int = 0
    ticks_total: int = 0
    bars_closed_m1: int = 0
    bars_closed_m15: int = 0
    last_tick_at: Optional[float] = None
    last_latency_ms: Optional[float] = None
    last_error: Optional[str] = None
    last_seen: Dict[int, float] = field(default_factory=dict)


def insert_ticks(conn: sqlite3.Connection, quotes: Sequence[IQActiveQuote]) -> None:
    conn.executemany(
        """
        INSERT INTO ticks (
            active_id, provider_name, ticker, is_otc, ts, price, bid, ask,
            payout_turbo_pct, payout_binary_pct, session_open, session_close,
            latency_ms, ts_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                q.active_id,
                q.provider_name,
                q.ticker,
                int(q.is_otc),
                q.received_at,
                q.price,
                q.bid,
                q.ask,
                q.payout_turbo_pct,
                q.payout_binary_pct,
                q.session_open,
                q.session_close,
                q.latency_ms,
                "local_receive",
            )
            for q in quotes
        ],
    )


def upsert_bars(conn: sqlite3.Connection, bars: Sequence[Bar]) -> None:
    conn.executemany(
        """
        INSERT INTO bars (
            active_id, provider_name, timeframe, open_time, open, high, low,
            close, bid_open, bid_close, ask_open, ask_close, ticks,
            first_tick_ts, last_tick_ts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(active_id, timeframe, open_time) DO UPDATE SET
            high = MAX(bars.high, excluded.high),
            low = MIN(bars.low, excluded.low),
            close = excluded.close,
            bid_close = COALESCE(excluded.bid_close, bars.bid_close),
            ask_close = COALESCE(excluded.ask_close, bars.ask_close),
            ticks = bars.ticks + excluded.ticks,
            first_tick_ts = MIN(
                COALESCE(bars.first_tick_ts, excluded.first_tick_ts),
                COALESCE(excluded.first_tick_ts, bars.first_tick_ts)
            ),
            last_tick_ts = MAX(
                COALESCE(bars.last_tick_ts, excluded.last_tick_ts),
                COALESCE(excluded.last_tick_ts, bars.last_tick_ts)
            )
        """,
        [
            (
                b.active_id,
                b.provider_name,
                b.timeframe,
                b.open_time,
                b.open,
                b.high,
                b.low,
                b.close,
                b.bid_open,
                b.bid_close,
                b.ask_open,
                b.ask_close,
                b.ticks,
                b.first_tick_ts,
                b.last_tick_ts,
            )
            for b in bars
        ],
    )


def replace_chart_quotes(
    conn: sqlite3.Connection,
    charts: Sequence[IQChart],
    *,
    fetched_at: Optional[float] = None,
) -> int:
    """Reemplaza la ventana de ``charts`` de cada activo/período.

    ``d1`` es una ventana móvil de 24 h. Guardar solo la última ventana evita
    acumular duplicados con timestamps ligeramente distintos en cada refresco.
    """
    ahora = time.time() if fetched_at is None else float(fetched_at)
    total = 0
    try:
        for chart in charts:
            if not chart.quotes:
                continue
            conn.execute(
                "DELETE FROM chart_quotes WHERE active_id=? AND period=?",
                (chart.active_id, chart.period),
            )
            conn.executemany(
                """
                INSERT INTO chart_quotes (
                    active_id, provider_name, period, ts, price, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chart.active_id,
                        chart.provider_name,
                        chart.period,
                        quote.timestamp,
                        quote.price,
                        ahora,
                    )
                    for quote in chart.quotes
                ],
            )
            total += len(chart.quotes)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return total


def refresh_charts(
    conn: sqlite3.Connection,
    client: IQPublicClient,
    ids: Sequence[int],
    *,
    period: str = DEFAULT_CHART_PERIOD,
) -> int:
    """Descarga y persiste los charts. Un fallo no afecta la recolección."""
    try:
        charts = client.fetch_charts(ids, period=period)
    except Exception as exc:
        LOGGER.warning("No se pudieron actualizar charts.%s: %s", period, exc)
        return 0
    if not charts:
        LOGGER.warning("charts.%s no devolvió datos para %s", period, list(ids))
        return 0
    saved = replace_chart_quotes(conn, charts)
    LOGGER.info(
        "charts.%s actualizado: %d puntos (%s)",
        period,
        saved,
        ", ".join(f"{c.provider_name}={len(c.quotes)}" for c in charts),
    )
    return saved


def write_health(
    conn: sqlite3.Connection,
    *,
    status: str,
    stats: RuntimeStats,
    last_tick_age_s: Optional[float],
    detail: str = "",
) -> None:
    bars_m1 = int(conn.execute("SELECT COUNT(*) FROM bars WHERE timeframe='M1'").fetchone()[0])
    bars_m15 = int(conn.execute("SELECT COUNT(*) FROM bars WHERE timeframe='M15'").fetchone()[0])
    conn.execute(
        """
        INSERT INTO collector_health (
            ts, status, last_tick_age_s, latency_ms, requests_total,
            errors_total, consecutive_errors, ticks_total,
            bars_m1_total, bars_m15_total, detail
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            time.time(),
            status,
            last_tick_age_s,
            stats.last_latency_ms,
            stats.requests_total,
            stats.errors_total,
            stats.consecutive_errors,
            stats.ticks_total,
            bars_m1,
            bars_m15,
            detail[:1000] if detail else "",
        ),
    )
    conn.commit()


def oldest_asset_age(stats: RuntimeStats, ids: Sequence[int]) -> Optional[float]:
    """Edad del activo más atrasado. Detecta que desaparezca uno solo."""
    if not ids:
        return None
    references = [stats.last_seen.get(active_id, stats.started_at) for active_id in ids]
    return max(0.0, time.time() - min(references))


def stale_ids(stats: RuntimeStats, ids: Sequence[int], threshold: float) -> List[int]:
    now = time.time()
    return [
        active_id
        for active_id in ids
        if (now - stats.last_seen.get(active_id, stats.started_at)) > threshold
    ]


def prune_ticks(conn: sqlite3.Connection, keep_days: float) -> int:
    """Borra ticks viejos; las velas M1/M15 se conservan intactas."""
    if keep_days <= 0:
        return 0
    cutoff = time.time() - float(keep_days) * 86400.0
    cursor = conn.execute("DELETE FROM ticks WHERE ts < ?", (cutoff,))
    deleted = int(cursor.rowcount or 0)
    conn.commit()
    return deleted


# ---------------------------------------------------------------------------
# ntfy
# ---------------------------------------------------------------------------

class NtfyNotifier:
    """Envío simple a ntfy. Topic propio para no mezclar con señales reales."""

    def __init__(
        self,
        server: str,
        topic: str,
        enabled: bool = True,
        user: str = "",
        password: str = "",
    ) -> None:
        self.server = (server or DEFAULT_NTFY_SERVER).rstrip("/")
        self.topic = (topic or "").strip()
        self.enabled = bool(enabled and self.topic)
        self.user = (user or "").strip()
        self.password = password or ""

    def send(
        self,
        text: str,
        *,
        title: str = "PIVOT OTC collector",
        priority: str = "default",
        tags: str = "chart_with_upwards_trend",
    ) -> bool:
        if not self.enabled:
            LOGGER.debug("ntfy deshabilitado o sin topic")
            return False
        url = f"{self.server}/{self.topic}"
        headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "Title": title,
            "Priority": priority,
            "Tags": tags,
        }
        if self.user and self.password:
            token = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
            headers["Authorization"] = "Basic " + token
        request = urllib.request.Request(
            url,
            data=text.encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                if 200 <= int(getattr(response, "status", 200)) < 300:
                    return True
                LOGGER.warning("ntfy respondió HTTP %s", getattr(response, "status", "?"))
                return False
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:200]
            except Exception:
                pass
            LOGGER.warning("ntfy falló HTTP %s: %s", exc.code, detail.strip())
            return False
        except Exception as exc:
            LOGGER.warning("ntfy falló: %s", exc)
            return False


class AlertManager:
    """Envía solo cambios de estado; repite errores cada `cooldown` segundos."""

    def __init__(self, notifier: NtfyNotifier, cooldown: float = 900.0) -> None:
        self.notifier = notifier
        self.cooldown = float(cooldown)
        self.state = "ok"
        self.last_sent = 0.0

    def set(self, state: str, text: str, *, priority: str = "default", tags: str = "warning") -> bool:
        now = time.monotonic()
        if state == self.state:
            if state == "ok":
                return False
            if (now - self.last_sent) < self.cooldown:
                return False
        sent = self.notifier.send(text, priority=priority, tags=tags)
        self.state = state
        self.last_sent = now
        return sent


def format_quotes(quotes: Sequence[IQActiveQuote]) -> str:
    lines = []
    for quote in sorted(quotes, key=lambda q: q.provider_name):
        payout = f"{quote.payout_turbo_pct:.0f}%" if quote.payout_turbo_pct is not None else "?"
        lines.append(f"• {quote.provider_name}: {quote.price:.6g} (Turbo {payout})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------

class FileLock:
    """Evita dos collectors escribiendo la misma SQLite."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = open(self.path, "a+", encoding="utf-8")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._handle.close()
            self._handle = None
            raise RuntimeError(f"Ya hay un collector usando {self.path}") from exc
        self._handle.seek(0)
        self._handle.truncate()
        self._handle.write(str(os.getpid()))
        self._handle.flush()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._handle is not None:
            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            finally:
                self._handle.close()
                self._handle = None


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------

def cmd_once(db_path: Path, ids: Sequence[int], timeout: float) -> int:
    client = IQPublicClient(timeout=timeout)
    try:
        quotes = client.fetch_actives(ids)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    finally:
        client.close()

    lock_path = db_path.parent / "collector.lock"
    try:
        with FileLock(lock_path):
            conn = connect_db(db_path)
            ensure_schema(conn)
            builder = BarBuilder()
            closed: List[Bar] = []
            for quote in quotes:
                closed.extend(builder.add(quote))

            stats = RuntimeStats(
                requests_total=1,
                ticks_total=len(quotes),
                last_tick_at=max(q.received_at for q in quotes),
                last_latency_ms=quotes[0].latency_ms,
            )
            now = time.time()
            for quote in quotes:
                stats.last_seen[quote.active_id] = now

            insert_ticks(conn, quotes)
            if closed:
                upsert_bars(conn, closed)
                for bar in closed:
                    if bar.timeframe == "M1":
                        stats.bars_closed_m1 += 1
                    elif bar.timeframe == "M15":
                        stats.bars_closed_m15 += 1
            conn.commit()
            write_health(
                conn,
                status="ok",
                stats=stats,
                last_tick_age_s=oldest_asset_age(stats, ids),
                detail="once",
            )
            conn.close()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    payload = {
        "ok": True,
        "db": str(db_path),
        "quotes": [
            {
                "active_id": q.active_id,
                "provider_name": q.provider_name,
                "price": q.price,
                "bid": q.bid,
                "ask": q.ask,
                "payout_turbo_pct": q.payout_turbo_pct,
                "payout_binary_pct": q.payout_binary_pct,
                "latency_ms": round(q.latency_ms, 1),
            }
            for q in quotes
        ],
        "closed_bars": [
            {
                "provider_name": b.provider_name,
                "timeframe": b.timeframe,
                "open_time": iso_utc(b.open_time),
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "ticks": b.ticks,
            }
            for b in closed
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_charts(db_path: Path, ids: Sequence[int], timeout: float) -> int:
    """Descarga ``charts.d1`` una vez y lo persiste en la DB."""
    client = IQPublicClient(timeout=timeout)
    try:
        charts = client.fetch_charts(ids)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    finally:
        client.close()

    lock_path = db_path.parent / "collector.lock"
    try:
        with FileLock(lock_path):
            conn = connect_db(db_path)
            ensure_schema(conn)
            saved = replace_chart_quotes(conn, charts)
            conn.close()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    payload = {
        "ok": True,
        "db": str(db_path),
        "saved": saved,
        "charts": [
            {
                "active_id": c.active_id,
                "provider_name": c.provider_name,
                "period": c.period,
                "points": len(c.quotes),
                "from": iso_utc(c.quotes[0].timestamp) if c.quotes else None,
                "to": iso_utc(c.quotes[-1].timestamp) if c.quotes else None,
            }
            for c in charts
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_loop(
    db_path: Path,
    ids: Sequence[int],
    interval: float,
    stale_after: float,
    health_every: float,
    notifier: NtfyNotifier,
    timeout: float,
    keep_ticks_days: float,
    chart_refresh: float = DEFAULT_CHART_REFRESH,
) -> int:
    lock_path = db_path.parent / "collector.lock"
    try:
        lock = FileLock(lock_path)
        lock.__enter__()
    except RuntimeError as exc:
        LOGGER.error("%s", exc)
        return 2

    stop = threading.Event()

    def _handle_signal(signum, _frame):
        LOGGER.info("Señal %s recibida, cerrando collector", signum)
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle_signal)
        except (ValueError, OSError):
            pass

    conn = connect_db(db_path)
    ensure_schema(conn)
    try:
        deleted = prune_ticks(conn, keep_ticks_days)
        if deleted:
            LOGGER.info(
                "Ticks podados al arrancar: %d (retención %.0f días)",
                deleted,
                keep_ticks_days,
            )
    except Exception as exc:
        LOGGER.warning("No se pudieron podar ticks al arrancar: %s", exc)
    next_prune = time.monotonic() + 3600.0
    client = IQPublicClient(timeout=timeout)
    try:
        refresh_charts(conn, client, ids)
    except Exception as exc:
        LOGGER.warning("No se pudo hacer el charts inicial: %s", exc)
    next_charts = time.monotonic() + chart_refresh
    builder = BarBuilder()
    stats = RuntimeStats()
    alerts = AlertManager(notifier)

    try:
        write_health(
            conn,
            status="starting",
            stats=stats,
            last_tick_age_s=None,
            detail="startup",
        )
    except Exception as exc:
        LOGGER.warning("No se pudo escribir salud de arranque: %s", exc)

    startup = (
        "🟢 PIVOT OTC collector iniciado\n"
        f"IDs: {', '.join(str(i) for i in ids)}\n"
        f"Intervalo: {interval:.1f}s\n"
        f"DB: {db_path}"
    )
    notifier.send(startup, tags="white_check_mark")
    alerts.state = "ok"
    alerts.last_sent = time.monotonic()

    LOGGER.info(
        "Collector iniciado: ids=%s interval=%.1fs stale_after=%.0fs db=%s",
        list(ids),
        interval,
        stale_after,
        db_path,
    )

    next_health = time.monotonic() + health_every
    try:
        while not stop.is_set():
            cycle_start = time.monotonic()
            wait_s = interval
            try:
                quotes = client.fetch_actives(ids)
                now = time.time()
                stats.requests_total += 1
                stats.ticks_total += len(quotes)
                stats.last_tick_at = max(q.received_at for q in quotes)
                stats.last_latency_ms = quotes[0].latency_ms
                stats.consecutive_errors = 0
                stats.last_error = None
                for quote in quotes:
                    stats.last_seen[quote.active_id] = now

                insert_ticks(conn, quotes)

                closed: List[Bar] = []
                for quote in quotes:
                    closed.extend(builder.add(quote))
                if closed:
                    upsert_bars(conn, closed)
                    for bar in closed:
                        if bar.timeframe == "M1":
                            stats.bars_closed_m1 += 1
                        elif bar.timeframe == "M15":
                            stats.bars_closed_m15 += 1
                    LOGGER.info(
                        "Velas cerradas: %s",
                        ", ".join(
                            f"{b.provider_name} {b.timeframe} {iso_utc(b.open_time)}"
                            for b in closed
                        ),
                    )
                conn.commit()

                missing = [active_id for active_id in ids if active_id not in stats.last_seen]
                if missing:
                    LOGGER.warning("Activos ausentes en la respuesta: %s", missing)
                LOGGER.debug(
                    "Lote OK: %s (latencia %.0fms)",
                    ", ".join(f"{q.provider_name}={q.price:.6g}" for q in quotes),
                    quotes[0].latency_ms,
                )
            except Exception as exc:
                stats.requests_total += 1
                stats.errors_total += 1
                stats.consecutive_errors += 1
                stats.last_error = str(exc)
                LOGGER.error(
                    "Error consultando IQ pública (%d consecutivos): %s",
                    stats.consecutive_errors,
                    exc,
                )
                if stats.consecutive_errors >= 3:
                    alerts.set(
                        "error",
                        "🔴 PIVOT OTC collector con errores\n"
                        f"Fallos consecutivos: {stats.consecutive_errors}\n"
                        f"Último error: {str(exc)[:300]}",
                        priority="high",
                        tags="rotating_light",
                    )
                wait_s = min(interval * (2 ** min(stats.consecutive_errors - 1, 5)), 30.0)

            now_mono = time.monotonic()
            if now_mono >= next_health:
                age = oldest_asset_age(stats, ids)
                if stats.consecutive_errors >= 3:
                    status = "error"
                elif age is not None and age > stale_after:
                    status = "stale"
                else:
                    status = "ok"

                late = stale_ids(stats, ids, stale_after)
                detail = stats.last_error or ""
                if late:
                    detail = (detail + f" | sin datos frescos: {late}").strip(" |")
                write_health(
                    conn,
                    status=status,
                    stats=stats,
                    last_tick_age_s=age,
                    detail=detail,
                )
                LOGGER.info(
                    "Salud: status=%s age=%.1fs latency=%s ticks=%d m1=%d m15=%d",
                    status,
                    age if age is not None else -1.0,
                    f"{stats.last_latency_ms:.0f}ms" if stats.last_latency_ms is not None else "?",
                    stats.ticks_total,
                    stats.bars_closed_m1,
                    stats.bars_closed_m15,
                )

                if status == "error":
                    alerts.set(
                        "error",
                        "🔴 PIVOT OTC collector con errores\n"
                        f"Fallos consecutivos: {stats.consecutive_errors}\n"
                        f"Último error: {(stats.last_error or '')[:300]}",
                        priority="high",
                        tags="rotating_light",
                    )
                elif status == "stale":
                    alerts.set(
                        "stale",
                        "🟠 PIVOT OTC collector sin datos frescos\n"
                        f"Activo más atrasado: {age:.0f}s\n"
                        f"IDs atrasados: {late or 'todos'}\n"
                        f"Último error: {stats.last_error or 'ninguno'}",
                        priority="default",
                        tags="warning",
                    )
                elif alerts.state != "ok":
                    age_text = f"{age:.1f}s" if age is not None else "?"
                    latency_text = (
                        f"{stats.last_latency_ms:.0f}ms"
                        if stats.last_latency_ms is not None
                        else "?"
                    )
                    alerts.set(
                        "ok",
                        "🟢 PIVOT OTC collector recuperado\n"
                        f"Último tick: hace {age_text}\n"
                        f"Latencia: {latency_text}",
                        tags="white_check_mark",
                    )

                next_health = now_mono + health_every

            if now_mono >= next_charts:
                try:
                    refresh_charts(conn, client, ids)
                except Exception as exc:
                    LOGGER.warning("No se pudieron actualizar los charts: %s", exc)
                next_charts = now_mono + chart_refresh

            if now_mono >= next_prune:
                try:
                    deleted = prune_ticks(conn, keep_ticks_days)
                    if deleted:
                        LOGGER.info(
                            "Ticks podados: %d (retención %.0f días)",
                            deleted,
                            keep_ticks_days,
                        )
                except Exception as exc:
                    LOGGER.warning("No se pudieron podar ticks: %s", exc)
                next_prune = now_mono + 3600.0

            elapsed = time.monotonic() - cycle_start
            wait = max(0.0, wait_s - elapsed)
            if wait > 0:
                stop.wait(wait)
    finally:
        age = oldest_asset_age(stats, ids)
        try:
            write_health(
                conn,
                status="stopped",
                stats=stats,
                last_tick_age_s=age,
                detail="shutdown",
            )
        except Exception as exc:
            LOGGER.warning("No se pudo escribir salud de cierre: %s", exc)
        partial = builder.flush()
        if partial:
            try:
                upsert_bars(conn, partial)
                conn.commit()
                LOGGER.info(
                    "Velas en curso guardadas como parciales: %d", len(partial)
                )
            except Exception as exc:
                LOGGER.warning("No se pudieron guardar las velas parciales: %s", exc)
        try:
            conn.commit()
        except Exception:
            pass
        conn.close()
        client.close()
        notifier.send(
            "⚪ PIVOT OTC collector detenido\n"
            f"Ticks: {stats.ticks_total}\n"
            f"M1: {stats.bars_closed_m1} | M15: {stats.bars_closed_m15}",
            tags="stop_sign",
        )
        lock.__exit__(None, None, None)
        LOGGER.info("Collector detenido")

    return 0


def cmd_status(db_path: Path) -> int:
    if not db_path.exists():
        print(f"No existe la DB: {db_path}")
        print("Ejecuta primero: python scripts/iq_public_collector.py --once")
        return 0

    try:
        conn = connect_db(db_path, readonly=True)
    except Exception as exc:
        print(f"No se pudo abrir la DB: {exc}")
        return 1

    size_mb = db_size_bytes(db_path) / (1024 * 1024)
    print(f"DB: {db_path} ({size_mb:.1f} MB)")
    print()

    tick_rows = conn.execute(
        """
        SELECT provider_name, COUNT(*) AS n, MIN(ts) AS first_ts, MAX(ts) AS last_ts
        FROM ticks
        GROUP BY provider_name
        ORDER BY provider_name
        """
    ).fetchall()
    total_ticks = sum(int(row["n"]) for row in tick_rows)
    print(f"Ticks ({total_ticks}):")
    if not tick_rows:
        print("  (sin datos)")
    for row in tick_rows:
        age = max(0.0, time.time() - float(row["last_ts"]))
        print(
            f"  {row['provider_name']:<14} {int(row['n']):>8}  "
            f"last={iso_utc(row['last_ts'])}  age={age:.1f}s"
        )
    print()

    bar_rows = conn.execute(
        """
        SELECT provider_name, timeframe, COUNT(*) AS n,
               MIN(open_time) AS first_time, MAX(open_time) AS last_time
        FROM bars
        GROUP BY provider_name, timeframe
        ORDER BY provider_name, timeframe
        """
    ).fetchall()
    print("Bars:")
    if not bar_rows:
        print("  (sin datos)")
    for row in bar_rows:
        print(
            f"  {row['provider_name']:<14} {row['timeframe']:<3} "
            f"{int(row['n']):>6}  from={iso_utc(row['first_time'])}  "
            f"to={iso_utc(row['last_time'])}"
        )
    print()

    try:
        chart_rows = conn.execute(
            """
            SELECT provider_name, period, COUNT(*) AS n,
                   MIN(ts) AS first_ts, MAX(ts) AS last_ts,
                   MAX(fetched_at) AS fetched_at
            FROM chart_quotes
            GROUP BY provider_name, period
            ORDER BY provider_name, period
            """
        ).fetchall()
    except sqlite3.OperationalError:
        chart_rows = []
    print("Charts:")
    if not chart_rows:
        print("  (sin datos)")
    for row in chart_rows:
        print(
            f"  {row['provider_name']:<14} {row['period']:<3} "
            f"{int(row['n']):>4} puntos  from={iso_utc(row['first_ts'])}  "
            f"to={iso_utc(row['last_ts'])}  "
            f"fetch_age={max(0.0, time.time() - float(row['fetched_at'])):.0f}s"
        )
    print()

    health = conn.execute(
        "SELECT * FROM collector_health ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if health is None:
        print("Salud: sin registros")
    else:
        age = health["last_tick_age_s"]
        print(
            f"Salud: {health['status']}  age={age:.1f}s"
            if age is not None
            else f"Salud: {health['status']}  age=?"
        )
        print(
            f"  ts={iso_utc(health['ts'])}  latency={health['latency_ms'] or 0:.0f}ms  "
            f"requests={health['requests_total']}  errors={health['errors_total']}"
        )
        print(
            f"  M1={health['bars_m1_total']}  M15={health['bars_m15_total']}  "
            f"detail={health['detail'] or '-'}"
        )

    conn.close()
    return 0


def human_seconds(seconds: float) -> str:
    if seconds < 120:
        return f"{seconds:.0f}s"
    if seconds < 7200:
        return f"{seconds / 60.0:.1f}m"
    return f"{seconds / 3600.0:.1f}h"


def cmd_quality(db_path: Path, since_hours: float = 0.0) -> int:
    if not db_path.exists():
        print(f"No existe la DB: {db_path}")
        return 1

    conn = connect_db(db_path, readonly=True)
    now = time.time()
    window_start = now - float(since_hours) * 3600.0 if since_hours > 0 else 0.0
    print(f"DB: {db_path} ({db_size_bytes(db_path) / (1024 * 1024):.1f} MB)")
    if window_start:
        print(f"Ventana: últimas {float(since_hours):g} h (desde {iso_utc(window_start)} UTC)")
    else:
        print("Ventana: todo el histórico")
    print()

    rows = conn.execute(
        """
        WITH deltas AS (
            SELECT active_id, provider_name, ts,
                   ts - LAG(ts) OVER (PARTITION BY active_id ORDER BY ts) AS delta
            FROM ticks
            WHERE ts >= ?
        )
        SELECT active_id, provider_name, COUNT(*) AS n,
               MIN(ts) AS first_ts, MAX(ts) AS last_ts,
               AVG(delta) AS avg_delta, MAX(delta) AS max_delta,
               SUM(CASE WHEN delta > 5 THEN 1 ELSE 0 END) AS gaps_5s,
               SUM(CASE WHEN delta > 15 THEN 1 ELSE 0 END) AS gaps_15s
        FROM deltas
        GROUP BY active_id, provider_name
        ORDER BY provider_name
        """,
        (window_start,),
    ).fetchall()

    jumps = {
        int(row["active_id"]): float(row["max_jump"] or 0.0)
        for row in conn.execute(
            """
            WITH jumps AS (
                SELECT active_id,
                       price - LAG(price) OVER (PARTITION BY active_id ORDER BY ts) AS dp
                FROM ticks
                WHERE ts >= ?
            )
            SELECT active_id, MAX(ABS(dp)) AS max_jump
            FROM jumps
            GROUP BY active_id
            """,
            (window_start,),
        ).fetchall()
    }

    issues: List[str] = []
    print("Ticks:")
    if not rows:
        print("  (sin datos)")
    for row in rows:
        n = int(row["n"])
        first_ts = float(row["first_ts"])
        last_ts = float(row["last_ts"])
        span = max(0.0, last_ts - first_ts)
        fresh = max(0.0, now - last_ts)
        avg_delta = float(row["avg_delta"] or 0.0)
        max_delta = float(row["max_delta"] or 0.0)
        gaps_5s = int(row["gaps_5s"] or 0)
        gaps_15s = int(row["gaps_15s"] or 0)
        print(
            f"  {row['provider_name']:<14} n={n:<7} span={human_seconds(span):>6} "
            f"avg={avg_delta:.2f}s max={max_delta:.1f}s gaps>5s={gaps_5s} "
            f"gaps>15s={gaps_15s} fresh={fresh:.1f}s "
            f"jump={jumps.get(int(row['active_id']), 0.0):.6g}"
        )
        if fresh > 60:
            issues.append(f"{row['provider_name']} datos viejos")
        if gaps_15s:
            issues.append(f"{row['provider_name']} {gaps_15s} gaps >15s")

    print()
    bar_rows = conn.execute(
        """
        SELECT provider_name, timeframe, COUNT(*) AS n,
               MIN(open_time) AS first_time, MAX(open_time) AS last_time,
               MIN(ticks) AS min_ticks, AVG(ticks) AS avg_ticks, MAX(ticks) AS max_ticks
        FROM bars
        WHERE open_time >= ?
        GROUP BY provider_name, timeframe
        ORDER BY provider_name, timeframe
        """,
        (int(window_start),),
    ).fetchall()

    tf_seconds = {"M1": 60, "M15": 900}
    print("Bars:")
    if not bar_rows:
        print("  (sin datos)")
    for row in bar_rows:
        n = int(row["n"])
        first_time = int(row["first_time"])
        last_time = int(row["last_time"])
        span = max(0, last_time - first_time)
        expected = span // tf_seconds.get(row["timeframe"], 60) + 1 if span >= 0 else n
        coverage = 100.0 * n / expected if expected else 100.0
        print(
            f"  {row['provider_name']:<14} {row['timeframe']:<3} n={n:<5} "
            f"expected~{expected:<5} coverage={coverage:5.1f}% "
            f"ticks min/avg/max={int(row['min_ticks'])}/"
            f"{float(row['avg_ticks'] or 0):.0f}/{int(row['max_ticks'])}"
        )
        if coverage < 95:
            issues.append(f"{row['provider_name']} {row['timeframe']} cobertura {coverage:.0f}%")

    print()
    health_window = max(86400.0, float(since_hours) * 3600.0)
    health = conn.execute(
        """
        SELECT COUNT(*) AS rows,
               SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors,
               SUM(CASE WHEN status='stale' THEN 1 ELSE 0 END) AS stales
        FROM collector_health
        WHERE ts >= ?
        """,
        (now - health_window,),
    ).fetchone()
    errors = int(health["errors"] or 0)
    stales = int(health["stales"] or 0)
    health_label = f"{health_window / 3600.0:g}h"
    print(f"Salud {health_label}: rows={int(health['rows'])} errors={errors} stales={stales}")
    if errors or stales:
        issues.append(f"eventos de salud en {health_label}")

    print()
    print("Veredicto:", "✅ sin issues" if not issues else "⚠ " + "; ".join(issues))
    conn.close()
    return 0


def cmd_export(db_path: Path, out_dir: Path) -> int:
    if not db_path.exists():
        print(f"No existe la DB: {db_path}")
        return 1

    conn = connect_db(db_path, readonly=True)
    pairs = conn.execute(
        """
        SELECT DISTINCT provider_name, timeframe
        FROM bars
        ORDER BY provider_name, timeframe
        """
    ).fetchall()
    if not pairs:
        print("No hay velas para exportar")
        conn.close()
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    for pair in pairs:
        provider_name = pair["provider_name"]
        timeframe = pair["timeframe"]
        rows = conn.execute(
            """
            SELECT open_time, open, high, low, close, ticks
            FROM bars
            WHERE provider_name=? AND timeframe=?
            ORDER BY open_time
            """,
            (provider_name, timeframe),
        ).fetchall()
        filename = f"{provider_name.lower()}_{timeframe.lower()}.csv"
        path = out_dir / filename
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["timestamp", "open", "high", "low", "close", "volume", "ticks", "provider_name"]
            )
            for row in rows:
                writer.writerow(
                    [
                        csv_ts(row["open_time"]),
                        row["open"],
                        row["high"],
                        row["low"],
                        row["close"],
                        0,
                        row["ticks"],
                        provider_name,
                    ]
                )
        print(f"{filename}: {len(rows)} velas -> {path}")

    conn.close()
    return 0


def cmd_ntfy_test(notifier: NtfyNotifier) -> int:
    if not notifier.enabled:
        print("ntfy deshabilitado (sin topic o --no-ntfy)")
        return 1

    text = (
        "🔧 TEST — PIVOT OTC collector\n"
        "Si ves esto, ntfy está configurado.\n"
        f"Topic: {notifier.topic}\n"
        f"Hora UTC: {iso_utc(time.time())}"
    )
    ok = notifier.send(text, title="PIVOT OTC test", tags="test_tube")
    print("OK" if ok else "FALLÓ")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collector read-only de precios OTC de IQ Option (GraphQL público)",
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--once", action="store_true", help="Una consulta y salir")
    actions.add_argument("--loop", action="store_true", help="Recolectar en bucle (default)")
    actions.add_argument("--status", action="store_true", help="Mostrar estado de la DB")
    actions.add_argument("--quality", action="store_true", help="Reporte de calidad: gaps, cobertura y salud")
    actions.add_argument("--export", action="store_true", help="Exportar velas a CSV")
    actions.add_argument("--charts", action="store_true", help="Descargar charts.d1 una vez y salir")
    actions.add_argument("--ntfy-test", action="store_true", help="Enviar un mensaje de prueba a ntfy")

    parser.add_argument(
        "--ids",
        default=os.getenv("IQ_PUBLIC_ACTIVE_IDS", DEFAULT_IDS),
        help=f"IDs separados por coma (default: {DEFAULT_IDS})",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.getenv("IQ_PUBLIC_INTERVAL", str(DEFAULT_INTERVAL))),
        help=f"Segundos entre consultas (default: {DEFAULT_INTERVAL})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("IQ_PUBLIC_TIMEOUT", "20")),
        help="Timeout HTTP en segundos (default: 20)",
    )
    parser.add_argument(
        "--db",
        default=os.getenv("IQ_PUBLIC_DB", str(DEFAULT_DB)),
        help="Ruta de la SQLite",
    )
    parser.add_argument(
        "--out-dir",
        default=os.getenv("IQ_PUBLIC_EXPORT_DIR", str(DEFAULT_EXPORT_DIR)),
        help="Directorio de exportación CSV",
    )
    parser.add_argument(
        "--stale-after",
        type=float,
        default=float(os.getenv("IQ_PUBLIC_STALE_AFTER", str(DEFAULT_STALE_AFTER))),
        help=f"Segundos sin datos para alertar (default: {DEFAULT_STALE_AFTER})",
    )
    parser.add_argument(
        "--health-every",
        type=float,
        default=float(os.getenv("IQ_PUBLIC_HEALTH_EVERY", str(DEFAULT_HEALTH_EVERY))),
        help=f"Segundos entre registros de salud (default: {DEFAULT_HEALTH_EVERY})",
    )
    parser.add_argument(
        "--keep-ticks-days",
        type=float,
        default=float(os.getenv("IQ_PUBLIC_KEEP_TICKS_DAYS", str(DEFAULT_KEEP_TICKS_DAYS))),
        help=f"Días de ticks crudos a conservar; 0 = infinito (default: {DEFAULT_KEEP_TICKS_DAYS})",
    )
    parser.add_argument(
        "--chart-refresh",
        type=float,
        default=float(os.getenv("IQ_PUBLIC_CHART_REFRESH", str(DEFAULT_CHART_REFRESH))),
        help=(
            "Segundos entre refrescos de charts.d1 "
            f"(default: {DEFAULT_CHART_REFRESH:g})"
        ),
    )
    parser.add_argument(
        "--since-hours",
        type=float,
        default=0.0,
        help="Limitar --quality a las últimas N horas (0 = todo el histórico)",
    )
    parser.add_argument(
        "--ntfy-topic",
        default=os.getenv("IQ_PUBLIC_NTFY_TOPIC", DEFAULT_NTFY_TOPIC),
        help=f"Topic ntfy de salud (default: {DEFAULT_NTFY_TOPIC})",
    )
    parser.add_argument(
        "--ntfy-server",
        default=os.getenv("IQ_PUBLIC_NTFY_SERVER", DEFAULT_NTFY_SERVER),
        help=f"Servidor ntfy (default: {DEFAULT_NTFY_SERVER})",
    )
    parser.add_argument(
        "--ntfy-user",
        default=os.getenv("IQ_PUBLIC_NTFY_USER", os.getenv("NTFY_USER", "")),
        help="Usuario ntfy (default: IQ_PUBLIC_NTFY_USER o NTFY_USER)",
    )
    parser.add_argument(
        "--ntfy-password",
        default=os.getenv("IQ_PUBLIC_NTFY_PASS", os.getenv("NTFY_PASS", "")),
        help="Password ntfy (default: IQ_PUBLIC_NTFY_PASS o NTFY_PASS)",
    )
    parser.add_argument(
        "--no-ntfy",
        action="store_true",
        help="Deshabilitar alertas ntfy",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("IQ_PUBLIC_LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Nivel de log (default: INFO)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not any(
        (
            args.once,
            args.loop,
            args.status,
            args.quality,
            args.export,
            args.charts,
            args.ntfy_test,
        )
    ):
        args.loop = True

    if args.interval < 0.25:
        parser.error("--interval debe ser >= 0.25 segundos")
    if args.timeout < 2:
        parser.error("--timeout debe ser >= 2 segundos")
    if args.stale_after < args.interval * 2:
        parser.error("--stale-after debe ser >= 2 * --interval")
    if args.health_every < 1:
        parser.error("--health-every debe ser >= 1 segundo")
    if args.keep_ticks_days < 0:
        parser.error("--keep-ticks-days debe ser >= 0")
    if args.chart_refresh < 60:
        parser.error("--chart-refresh debe ser >= 60 segundos")
    if args.since_hours < 0:
        parser.error("--since-hours debe ser >= 0")

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    db_path = resolve_path(args.db)
    out_dir = resolve_path(args.out_dir)
    notifier = NtfyNotifier(
        server=args.ntfy_server,
        topic=args.ntfy_topic,
        enabled=not args.no_ntfy,
        user=args.ntfy_user,
        password=args.ntfy_password,
    )

    if args.status:
        return cmd_status(db_path)
    if args.quality:
        return cmd_quality(db_path, float(args.since_hours))
    if args.export:
        return cmd_export(db_path, out_dir)
    if args.ntfy_test:
        return cmd_ntfy_test(notifier)

    try:
        ids = parse_ids(args.ids)
    except ValueError as exc:
        parser.error(str(exc))

    if args.charts:
        return cmd_charts(db_path, ids, float(args.timeout))
    if args.once:
        return cmd_once(db_path, ids, float(args.timeout))

    return cmd_loop(
        db_path=db_path,
        ids=ids,
        interval=float(args.interval),
        stale_after=float(args.stale_after),
        health_every=float(args.health_every),
        notifier=notifier,
        timeout=float(args.timeout),
        keep_ticks_days=float(args.keep_ticks_days),
        chart_refresh=float(args.chart_refresh),
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        LOGGER.exception("Error fatal: %s", exc)
        raise SystemExit(1)
