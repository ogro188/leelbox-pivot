# -*- coding: utf-8 -*-
"""
Cliente read-only para el GraphQL público de IQ Option.

No requiere API key, cookie, SSID ni cuenta. Solo consulta datos de mercado.
Este módulo no tiene ninguna capacidad de ejecutar órdenes.

Limitaciones conocidas (verificadas):
- El endpoint entrega precio, bid/ask, payout y sessionStat. No entrega velas
  OHLC: ``charts`` devuelve puntos de precio (`timestamp`, `price`) con una
  resolución de ~8 min en `d1`; el OHLC se aproxima agrupando esos puntos.
- La API no devuelve timestamp de servidor; `received_at` es hora local de
  recepción. La latencia se guarda para poder ajustar el análisis a posteriori.
- Es un endpoint no oficial: puede cambiar, limitar tasa o dejar de responder.
  El collector debe tratar los fallos como transitorios y no asumir SLA.

Símbolos canónicos: usar `providerName` (ej. "EURUSD-OTC"), no `ticker`
(ej. "EURUSD"), porque `ticker` no distingue OTC de real.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

logger = logging.getLogger(__name__)

IQ_PUBLIC_URL = "https://api.iqoption.com/v1/fininfo/graphql"
DEFAULT_TIMEOUT = 20.0
DEFAULT_RETRIES = 2

# El tipo del argumento es ActiveID, no Int. Verificado contra el endpoint.
ACTIVES_QUERY = """
query Actives($ids: [ActiveID!]!) {
  actives(ids: $ids) {
    id
    ticker
    providerName
    isOTC
    price
    quotation {
      ask
      bid
    }
    payoutTurbo: profitability(instrument: TurboOption)
    payoutBinary: profitability(instrument: BinaryOption)
    sessionStat {
      open
      close
    }
  }
}
""".strip()

TIMEFRAME_SECONDS: Dict[str, int] = {
    "M1": 60,
    "M15": 900,
}

# Períodos de ``active(id).charts`` verificados contra el endpoint público.
# La resolución depende del período: d1 ~8 min, w1 ~45 min, m1 ~4 h,
# y1 ~2 días, y5 ~7 días. Solo d1 se usa hoy para calentar M15.
CHART_PERIODS: Tuple[str, ...] = ("d1", "w1", "m1", "y1", "y5")

_CHART_QUERY_TEMPLATE = """
query Charts($ids: [ActiveID!]!) {
  actives(ids: $ids) {
    id
    providerName
    charts {
      %s {
        quotes(size: xxl) {
          timestamp
          price
        }
      }
    }
  }
}
""".strip()


class IQPublicError(RuntimeError):
    """Error de transporte, GraphQL o respuesta inválida del endpoint público."""


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalizar_ids(active_ids: Sequence[int]) -> List[int]:
    ids: List[int] = []
    for raw in active_ids:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in ids:
            ids.append(value)
    return ids


@dataclass(frozen=True)
class IQActiveQuote:
    """Una cotización puntual de un activo OTC."""

    active_id: int
    provider_name: str
    ticker: str
    is_otc: bool
    price: float
    bid: Optional[float]
    ask: Optional[float]
    payout_turbo_pct: Optional[float]
    payout_binary_pct: Optional[float]
    session_open: Optional[float]
    session_close: Optional[float]
    received_at: float
    latency_ms: float

    @classmethod
    def from_graphql(
        cls,
        item: Dict[str, Any],
        *,
        received_at: float,
        latency_ms: float,
    ) -> "IQActiveQuote":
        """Normaliza un nodo `actives` del GraphQL.

        Lanza ValueError si no hay un precio utilizable.
        """
        active_id = _as_int(item.get("id"))
        if active_id is None or active_id <= 0:
            raise ValueError(f"active_id inválido: {item.get('id')!r}")

        quotation = item.get("quotation") or {}
        bid = _as_float(quotation.get("bid"))
        ask = _as_float(quotation.get("ask"))
        price = _as_float(item.get("price"))
        if price is None and bid is not None and ask is not None:
            price = (bid + ask) / 2.0
        if price is None or price <= 0:
            raise ValueError(f"precio inválido para active_id={active_id}: {item.get('price')!r}")

        ticker = str(item.get("ticker") or "").strip()
        is_otc = bool(item.get("isOTC"))
        provider_name = str(item.get("providerName") or "").strip()
        if not provider_name:
            provider_name = f"{ticker}-OTC" if is_otc and ticker else (ticker or f"ACTIVE-{active_id}")

        session = item.get("sessionStat") or {}
        return cls(
            active_id=active_id,
            provider_name=provider_name,
            ticker=ticker,
            is_otc=is_otc,
            price=price,
            bid=bid,
            ask=ask,
            payout_turbo_pct=_as_float(item.get("payoutTurbo")),
            payout_binary_pct=_as_float(item.get("payoutBinary")),
            session_open=_as_float(session.get("open")),
            session_close=_as_float(session.get("close")),
            received_at=float(received_at),
            latency_ms=float(latency_ms),
        )


@dataclass(frozen=True)
class IQChartQuote:
    """Punto de precio histórico de ``active(id).charts``."""

    timestamp: int
    price: float


@dataclass(frozen=True)
class IQChart:
    """Serie histórica de un activo para un período de ``charts``."""

    active_id: int
    provider_name: str
    period: str
    quotes: Tuple[IQChartQuote, ...]


class IQPublicClient:
    """Cliente HTTP mínimo, sin autenticación, para el GraphQL público.

    Usa una `requests.Session` para reutilizar TCP/TLS entre polls. Sin
    keep-alive, cada consulta abría un handshake nuevo y la latencia pasaba
    de ~0.5 s a ~2-3 s.
    """

    def __init__(
        self,
        url: str = IQ_PUBLIC_URL,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.url = url
        self.timeout = float(timeout)
        self.retries = max(0, int(retries))
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "PivotOTCCollector/1.0 (read-only)",
            }
        )

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        last_error: Optional[BaseException] = None
        for attempt in range(self.retries + 1):
            try:
                response = self._session.post(
                    self.url,
                    json=payload,
                    timeout=self.timeout,
                )
                if int(response.status_code) != 200:
                    body = str(getattr(response, "text", ""))[:500]
                    raise IQPublicError(f"HTTP {response.status_code}: {body}".strip())

                try:
                    data = response.json()
                except ValueError as exc:
                    raise IQPublicError(f"Respuesta no JSON: {exc}") from exc

                errors = data.get("errors")
                if errors:
                    messages = []
                    for error in errors:
                        if isinstance(error, dict):
                            messages.append(str(error.get("message") or error))
                        else:
                            messages.append(str(error))
                    raise IQPublicError("GraphQL: " + "; ".join(messages))
                return data
            except Exception as exc:  # requests, JSON, GraphQL o bug de parseo
                last_error = exc

            if attempt < self.retries:
                time.sleep(0.4 * (2 ** attempt))

        raise IQPublicError(f"No se pudo consultar IQ pública: {last_error}") from last_error

    def fetch_actives(self, active_ids: Sequence[int]) -> List[IQActiveQuote]:
        """Consulta un lote de IDs y devuelve las cotizaciones válidas.

        Si el endpoint devuelve algunos activos inválidos, se omiten y se
        registra un warning. Si no queda ninguna cotización, lanza IQPublicError.
        """
        ids = _normalizar_ids(active_ids)
        if not ids:
            raise ValueError("active_ids vacío")

        payload = {
            "query": ACTIVES_QUERY,
            "variables": {"ids": ids},
        }
        started = time.monotonic()
        data = self._post(payload)
        received_at = time.time()
        latency_ms = (time.monotonic() - started) * 1000.0

        body = data.get("data") or {}
        actives = body.get("actives")
        if actives is None:
            raise IQPublicError(f"Respuesta sin data.actives: {data}")

        quotes: List[IQActiveQuote] = []
        for item in actives:
            if not isinstance(item, dict):
                continue
            try:
                quotes.append(
                    IQActiveQuote.from_graphql(
                        item,
                        received_at=received_at,
                        latency_ms=latency_ms,
                    )
                )
            except ValueError as exc:
                logger.warning("Cotización IQ omitida: %s", exc)

        if not quotes:
            raise IQPublicError("La respuesta no contiene cotizaciones válidas")
        return quotes

    def fetch_charts(
        self,
        active_ids: Sequence[int],
        period: str = "d1",
    ) -> List[IQChart]:
        """Descarga los puntos históricos de ``charts`` para un lote de IDs.

        Devuelve solo los activos con al menos una cotización válida. No lanza
        si un activo no tiene datos; sí lanza si la respuesta no trae
        ``data.actives`` o si el período no está soportado.
        """
        periodo = str(period or "d1").strip().lower()
        if periodo not in CHART_PERIODS:
            raise ValueError(
                f"Período de charts no soportado: {period!r} "
                f"(válidos: {', '.join(CHART_PERIODS)})"
            )
        ids = _normalizar_ids(active_ids)
        if not ids:
            raise ValueError("active_ids vacío")

        payload = {
            "query": _CHART_QUERY_TEMPLATE % periodo,
            "variables": {"ids": ids},
        }
        data = self._post(payload)

        body = data.get("data") or {}
        actives = body.get("actives")
        if actives is None:
            raise IQPublicError(f"Respuesta sin data.actives: {data}")

        charts: List[IQChart] = []
        for item in actives:
            if not isinstance(item, dict):
                continue
            active_id = _as_int(item.get("id"))
            if active_id is None or active_id <= 0:
                continue
            provider_name = str(item.get("providerName") or "").strip()
            if not provider_name:
                provider_name = f"ACTIVE-{active_id}"
            nodo = ((item.get("charts") or {}).get(periodo) or {})
            crudos = nodo.get("quotes") or []

            por_ts: Dict[int, float] = {}
            for quote in crudos:
                if not isinstance(quote, dict):
                    continue
                ts = _as_int(quote.get("timestamp"))
                price = _as_float(quote.get("price"))
                if ts is None or price is None or price <= 0:
                    continue
                por_ts[int(ts)] = float(price)

            if not por_ts:
                logger.warning(
                    "charts.%s sin cotizaciones para %s (%s)",
                    periodo,
                    provider_name,
                    active_id,
                )
                continue
            charts.append(
                IQChart(
                    active_id=active_id,
                    provider_name=provider_name,
                    period=periodo,
                    quotes=tuple(
                        IQChartQuote(timestamp=ts, price=price)
                        for ts, price in sorted(por_ts.items())
                    ),
                )
            )
        return charts


def bucket_start(timestamp: float, timeframe: str) -> int:
    """Inicio de la vela UTC que contiene `timestamp`."""
    try:
        seconds = TIMEFRAME_SECONDS[timeframe]
    except KeyError as exc:
        raise ValueError(f"Timeframe no soportado: {timeframe}") from exc
    return int(float(timestamp) // seconds) * seconds


@dataclass
class Bar:
    """Vela construida desde muestras puntuales. No es OHLC de exchange."""

    active_id: int
    provider_name: str
    timeframe: str
    open_time: int
    open: float
    high: float
    low: float
    close: float
    bid_open: Optional[float]
    bid_close: Optional[float]
    ask_open: Optional[float]
    ask_close: Optional[float]
    ticks: int
    first_tick_ts: float
    last_tick_ts: float


class BarBuilder:
    """Construye velas M1/M15 a partir de cotizaciones puntuales.

    - Alinea los inicios a epoch UTC.
    - Solo devuelve velas cerradas; la vela en curso queda en memoria.
    - Si hay un hueco, no inventa velas intermedias: cierra la anterior y
      arranca la nueva en el bucket del tick actual.
    - Los ticks atrasados (bucket anterior) se ignoran.
    """

    def __init__(self, timeframes: Sequence[str] = ("M1", "M15")) -> None:
        unknown = [tf for tf in timeframes if tf not in TIMEFRAME_SECONDS]
        if unknown:
            raise ValueError(f"Timeframes no soportados: {unknown}")
        self.timeframes: Tuple[str, ...] = tuple(timeframes)
        self._open: Dict[Tuple[int, str], Bar] = {}

    def add(self, quote: IQActiveQuote) -> List[Bar]:
        """Añade una cotización y devuelve las velas que se cerraron."""
        closed: List[Bar] = []
        for timeframe in self.timeframes:
            start = bucket_start(quote.received_at, timeframe)
            key = (quote.active_id, timeframe)
            current = self._open.get(key)

            if current is None:
                self._open[key] = self._new_bar(quote, timeframe, start)
                continue

            if start == current.open_time:
                self._update_bar(current, quote)
            elif start > current.open_time:
                closed.append(current)
                self._open[key] = self._new_bar(quote, timeframe, start)
            else:
                # Tick atrasado respecto de la vela en curso.
                logger.debug(
                    "Tick atrasado ignorado: %s %s ts=%s open_time=%s",
                    quote.provider_name,
                    timeframe,
                    quote.received_at,
                    current.open_time,
                )
        return closed

    def flush(self) -> List[Bar]:
        """Devuelve y olvida las velas en curso. No las marca como cerradas."""
        bars = list(self._open.values())
        self._open.clear()
        return bars

    def current(self, active_id: int, timeframe: str) -> Optional[Bar]:
        return self._open.get((active_id, timeframe))

    @staticmethod
    def _new_bar(quote: IQActiveQuote, timeframe: str, start: int) -> Bar:
        return Bar(
            active_id=quote.active_id,
            provider_name=quote.provider_name,
            timeframe=timeframe,
            open_time=start,
            open=quote.price,
            high=quote.price,
            low=quote.price,
            close=quote.price,
            bid_open=quote.bid,
            bid_close=quote.bid,
            ask_open=quote.ask,
            ask_close=quote.ask,
            ticks=1,
            first_tick_ts=quote.received_at,
            last_tick_ts=quote.received_at,
        )

    @staticmethod
    def _update_bar(bar: Bar, quote: IQActiveQuote) -> None:
        bar.high = max(bar.high, quote.price)
        bar.low = min(bar.low, quote.price)
        bar.close = quote.price
        if quote.bid is not None:
            if bar.bid_open is None:
                bar.bid_open = quote.bid
            bar.bid_close = quote.bid
        if quote.ask is not None:
            if bar.ask_open is None:
                bar.ask_open = quote.ask
            bar.ask_close = quote.ask
        bar.ticks += 1
        bar.last_tick_ts = quote.received_at


__all__ = [
    "IQ_PUBLIC_URL",
    "IQPublicClient",
    "IQPublicError",
    "IQActiveQuote",
    "IQChart",
    "IQChartQuote",
    "CHART_PERIODS",
    "Bar",
    "BarBuilder",
    "bucket_start",
    "TIMEFRAME_SECONDS",
]
