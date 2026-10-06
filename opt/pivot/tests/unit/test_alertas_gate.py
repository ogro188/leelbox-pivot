"""Guardas de origen de señales y bloqueo de ntfy en replay/test."""
import asyncio
import os
import tempfile

import pytest


def test_alertas_live_default_off(monkeypatch):
    monkeypatch.delenv("PIVOT_ALERTAS_LIVE", raising=False)
    from kernel.ntfy import alertas_live_habilitadas
    assert alertas_live_habilitadas() is False


def test_alertas_live_enable(monkeypatch):
    from kernel.ntfy import alertas_live_habilitadas
    monkeypatch.setenv("PIVOT_ALERTAS_LIVE", "1")
    assert alertas_live_habilitadas() is True
    monkeypatch.setenv("PIVOT_ALERTAS_LIVE", "0")
    assert alertas_live_habilitadas() is False


def test_enviar_bloqueado_sin_live(monkeypatch):
    monkeypatch.delenv("PIVOT_ALERTAS_LIVE", raising=False)
    from kernel.ntfy import enviar
    ok, detalle = enviar("EURUSD", "hola", {"topic": "t", "server": "https://ntfy.sh"})
    assert ok is False
    assert "PIVOT_ALERTAS_LIVE" in detalle


def test_enviar_forzar_salta_gate(monkeypatch):
    """forzar=True solo lo usa el endpoint de test de conectividad."""
    from kernel.ntfy import enviar

    class _Resp:
        status_code = 200

    def _post(*args, **kwargs):
        return _Resp()

    monkeypatch.setattr("kernel.ntfy.requests.post", _post)
    monkeypatch.delenv("PIVOT_ALERTAS_LIVE", raising=False)
    ok, detalle = enviar(
        "EURUSD", "test", {"topic": "t", "server": "https://ntfy.sh"}, forzar=True
    )
    assert ok is True


def test_send_ntfy_bloqueado_sin_live(monkeypatch):
    monkeypatch.delenv("PIVOT_ALERTAS_LIVE", raising=False)
    from core.alertas import AlertasEngine

    eng = AlertasEngine(ntfy_topic="radar_test", ntfy_server="https://ntfy.sh")
    assert eng.send_ntfy_message("x") is False


def test_guardar_senal_core_fuente_replay():
    from kernel.storage import Database
    from datetime import datetime, timezone

    with tempfile.TemporaryDirectory() as td:
        db = Database(os.path.join(td, "t.db"))
        try:
            db.initialize()

            async def run():
                await db.guardar_senal_core(
                    signal_id="R1",
                    entry_time=datetime(2024, 7, 1, tzinfo=timezone.utc),
                    symbol="EURUSD",
                    direction=1,
                    entry_price=1.08,
                    detector="D1",
                    tipo="PIVOT_D1",
                    hipotesis_prob_min=0.5,
                    hipotesis_prob_max=0.7,
                    hipotesis_expiry_velas=4,
                    conviccion=0.7,
                    regimen_volatilidad="NORMAL",
                    fuente="replay",
                )
                rows = await db.obtener_senales_core(symbol="EURUSD", limite=5)
                assert rows[0]["fuente"] == "replay"

            asyncio.run(run())
        finally:
            db.close()


def test_backfill_marca_pivot_como_replay():
    """Las etiquetas PIVOT_* solo las genera el replay/backtest."""
    from kernel.storage import Database
    from datetime import datetime, timezone

    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        db = Database(path)
        try:
            db.initialize()

            async def run():
                await db.guardar_senal_core(
                    signal_id="OLD",
                    entry_time=datetime(2024, 7, 1, tzinfo=timezone.utc),
                    symbol="EURUSD",
                    direction=1,
                    entry_price=1.08,
                    detector="D1",
                    tipo="PIVOT_D1",
                    hipotesis_prob_min=0.5,
                    hipotesis_prob_max=0.7,
                    hipotesis_expiry_velas=4,
                    conviccion=0.7,
                    regimen_volatilidad="NORMAL",
                    fuente="deriv",
                )

            asyncio.run(run())
            db.close()
            db._initialized = False
            db._conn = None
            db.initialize()
            row = db._get_connection().execute(
                "SELECT fuente FROM senales_core WHERE signal_id='OLD'"
            ).fetchone()
            assert row[0] == "replay"
        finally:
            db.close()


def test_replay_no_prefiere_csv_sintetico_real():
    """Ningún path de carga debe preferir eurusd_m15_real.csv (sintético)."""
    from pathlib import Path

    src = Path("kernel/api/app.py").read_text(encoding="utf-8")
    # No debe existir construcción de path hacia *_m15_real.csv
    assert '_m15_real.csv"' not in src
    assert "_m15_real.csv'" not in src
    assert "path_live" in src
    assert "_path_m15_para" in src


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
