"""Multi-coin + job ledger dashboard routes — they yearn for the mines."""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi.responses import JSONResponse

logger = logging.getLogger("aurora-dashboard.mining_coins")


def install_mining_coins_ops(app: Any, *, get_comms: Callable[[], Any]):
    @app.get("/mining/coins")
    def mining_coins():
        try:
            from mods.mining_engine.coins import list_coins

            return {
                "status": "ok",
                "coins": list_coins(),
                "note": "ETH mainnet is PoS — mine ETC for ethash-family PoW, BTC for SHA256d",
            }
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.get("/mining/jobs")
    def mining_jobs(limit: int = 20):
        try:
            from mods.mining_engine.job_ledger import JobLedger

            led = JobLedger(get_comms())
            return {"status": "ok", "items": led.recent(limit), "stats": led.stats()}
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    @app.get("/mining/yearn")
    def mining_yearn():
        """Swarm mood from job scores + hashrate."""
        try:
            from mods.mining_engine.job_ledger import JobLedger
            from dashboard.local_miner import local_status

            stats = JobLedger(get_comms()).stats()
            local = local_status(get_comms())
            running = bool(local.get("running"))
            score = float(stats.get("avg_score") or 0)
            if running and score >= 3:
                mood = "THEY YEARN FOR THE MINES"
            elif running:
                mood = "Hashing with quiet ambition"
            elif stats.get("count", 0) > 0:
                mood = "Remembering jobs of the past"
            else:
                mood = "Patiently waiting to yearn"
            return {
                "mood": mood,
                "job_stats": stats,
                "mining": {
                    "running": running,
                    "backend": local.get("backend"),
                    "hashrate_display": local.get("hashrate_display"),
                },
            }
        except Exception as e:
            return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

    logger.info("mining_coins_ops mounted")
