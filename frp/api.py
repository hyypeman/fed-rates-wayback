from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query

from frp import core

app = FastAPI(title="Fed Rate Wayback Machine API", version="0.1.0")
ROOT = Path.cwd()


@app.get("/events")
def events() -> dict:
    configs = []
    for path in sorted((ROOT / "configs/events").glob("*.yaml")):
        config = core.load_event_config(path)
        configs.append(
            {
                "event_id": config["event_id"],
                "event_slug": config["event_slug"],
                "title": config.get("title"),
                "evaluation_mode": config.get("evaluation_mode"),
                "config_path": str(path),
            }
        )
    return {"events": configs}


@app.get("/evidence")
def evidence(event_id: str = Query(...), as_of: str = Query(...)) -> dict:
    run_id = f"{event_id}_{core.compact_time(as_of)}"
    path = ROOT / "data/gold" / run_id / "prediction.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Run not found. Execute frp run first.")
    return core.evidence_bundle(run_id, ROOT)


@app.get("/snapshot/{snapshot_id}")
def snapshot(snapshot_id: str) -> dict:
    for path in (ROOT / "data/gold").glob("*/snapshot.json"):
        data = core.read_json(path)
        if data.get("snapshot_id") == snapshot_id:
            return data
    raise HTTPException(status_code=404, detail="Snapshot not found")


@app.get("/market-odds")
def market_odds(event_id: str = Query(...), as_of: str = Query(...)) -> dict:
    bundle = evidence(event_id, as_of)
    return {"event": bundle["event"], "market_odds": bundle["market_odds"]}


@app.get("/prediction")
def prediction(event_id: str = Query(...), as_of: str = Query(...)) -> dict:
    bundle = evidence(event_id, as_of)
    return {"event": bundle["event"], "prediction": bundle["prediction"]}


@app.get("/audit/{snapshot_id}")
def audit(snapshot_id: str) -> dict:
    for path in (ROOT / "outputs").glob("*/audit_report.json"):
        data = core.read_json(path)
        if data.get("snapshot_id") == snapshot_id:
            return data
    raise HTTPException(status_code=404, detail="Audit not found")
