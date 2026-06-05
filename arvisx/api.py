"""
ArvisX Phase-1b API — serves the residential dashboard.

Self-contained FastAPI app (separate from the commercial ARVIS API). Holds an
in-memory community (the simulator output for the prototype) and exposes the three
PRD dashboard views + per-asset grounded advisory.

Run:  python -m arvisx.api          # uvicorn on :8090
Endpoints (prefix /api/v1):
  GET  /community/overview          → service-health tiles
  GET  /community/risks             → active risks
  GET  /community/assets            → asset explorer
  GET  /community/report            → all three in one payload
  GET  /asset/{asset_id}/advisory   → grounded RCA advisory for one asset
  POST /scenario/{name}             → reset community state: "healthy" | "prd"
"""
from __future__ import annotations

import os
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List

from arvisx.health import assess_asset, build_report
from arvisx.simulator import healthy_community, inject_prd_scenario


def _jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses/enums/datetimes to JSON-safe values."""
    if is_dataclass(obj):
        return {k: _jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


class _State:
    """In-memory community for the prototype (stands in for live ingest)."""
    def __init__(self):
        self.assets = inject_prd_scenario()
        self.scenario = "prd"

    def set_scenario(self, name: str):
        if name == "healthy":
            self.assets = healthy_community()
        else:
            self.assets = inject_prd_scenario()
            name = "prd"
        self.scenario = name

    def asset(self, asset_id: str):
        return next((a for a in self.assets if a.asset_id == asset_id), None)


def create_app():
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="ArvisX — Residential Operations Intelligence", version="0.1.0-phase1b")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    state = _State()
    app.state.community = state

    @app.get("/api/v1/community/overview")
    async def overview():
        rep = build_report(state.assets)
        return {"scenario": state.scenario, "generated_at": rep.generated_at.isoformat(),
                "services": _jsonable(rep.services)}

    @app.get("/api/v1/community/risks")
    async def risks():
        rep = build_report(state.assets)
        return {"count": len(rep.risks), "risks": _jsonable(rep.risks)}

    @app.get("/api/v1/community/assets")
    async def assets():
        rep = build_report(state.assets)
        return {"count": len(rep.assets), "assets": _jsonable(rep.assets)}

    @app.get("/api/v1/community/report")
    async def report():
        return _jsonable(build_report(state.assets))

    @app.get("/api/v1/asset/{asset_id}/advisory")
    async def advisory(asset_id: str):
        from arvisx.advisory import investigate_asset
        a = state.asset(asset_id)
        if a is None:
            raise HTTPException(404, f"unknown asset {asset_id}")
        _, rks = assess_asset(a, datetime.now())
        llm = None
        if os.environ.get("ARVIS_X_LLM", "").strip() in ("1", "true", "True"):
            try:
                from agent_unified.llm import UnifiedLLM
                llm = UnifiedLLM()
            except Exception:
                llm = None
        adv = await investigate_asset(a, rks, llm=llm)
        return _jsonable(adv)

    @app.post("/api/v1/scenario/{name}")
    async def scenario(name: str):
        state.set_scenario(name)
        return {"status": "ok", "scenario": state.scenario, "assets": len(state.assets)}

    @app.get("/")
    async def root():
        return {"service": "ArvisX", "phase": "1b",
                "endpoints": ["/api/v1/community/overview", "/api/v1/community/risks",
                              "/api/v1/community/assets", "/api/v1/community/report",
                              "/api/v1/asset/{asset_id}/advisory", "/api/v1/scenario/{name}"]}
    return app


def main() -> int:
    import uvicorn
    port = int(os.environ.get("ARVISX_API_PORT", "8090"))
    uvicorn.run(create_app(), host="0.0.0.0", port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
