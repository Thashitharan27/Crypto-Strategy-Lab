"""Opt-in HTTP router for guarded job inspection. Not installed by production launcher.

The existing browser_http local-origin middleware must wrap any application
that includes this router. This router additionally authenticates every call.
"""
from __future__ import annotations

import secrets
import re

_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")


def create_guarded_job_router(*, token: str, integration, enabled: bool = False, audit_callback=None):
    from fastapi import APIRouter, Header, HTTPException
    router = APIRouter()
    if enabled is not True:
        return router
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("A browser bearer token is required")

    def audit(operation: str, outcome: str) -> None:
        # Never log IDs, payloads, tokens, result data or native exception text.
        if audit_callback is not None:
            try:
                audit_callback({"operation": operation, "outcome": outcome})
            except Exception:
                pass

    def authorize(authorization: str | None):
        supplied = authorization.removeprefix("Bearer ") if authorization else ""
        if not secrets.compare_digest(supplied, token):
            audit("AUTH", "DENIED")
            raise HTTPException(status_code=401, detail="Unauthorized")

    def invoke(request_id, call, operation):
        if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
            audit(operation, "INVALID_ID")
            raise HTTPException(status_code=404, detail="Unknown job")
        try:
            result = call()
            audit(operation, "SUCCESS")
            return result
        except KeyError:
            audit(operation, "NOT_FOUND")
            raise HTTPException(status_code=404, detail="Unknown job")
        except PermissionError:
            audit(operation, "DENIED")
            raise HTTPException(status_code=403, detail="Guarded operations disabled")

    @router.get("/api/v1/guarded/jobs/{request_id}")
    def status(request_id: str, authorization: str | None = Header(default=None)):
        authorize(authorization)
        return invoke(request_id, lambda: integration.status(request_id), "STATUS")

    @router.get("/api/v1/guarded/jobs/{request_id}/progress")
    def progress(request_id: str, authorization: str | None = Header(default=None)):
        authorize(authorization)
        return invoke(request_id, lambda: integration.progress(request_id), "PROGRESS")

    @router.post("/api/v1/guarded/jobs/{request_id}/cancel")
    def cancel(request_id: str, authorization: str | None = Header(default=None)):
        authorize(authorization)
        return invoke(request_id, lambda: integration.cancel(request_id), "CANCEL")

    @router.put("/api/v1/guarded/configs/{config_id}")
    def save_config(config_id: str, payload: dict, authorization: str | None = Header(default=None)):
        authorize(authorization)
        if not isinstance(config_id, str) or _REQUEST_ID.fullmatch(config_id) is None:
            audit("CONFIG_SAVE", "INVALID_ID")
            raise HTTPException(status_code=404, detail="Unknown configuration")
        try:
            integration.save_config(config_id, payload)
            audit("CONFIG_SAVE", "SUCCESS")
        except PermissionError:
            audit("CONFIG_SAVE", "DENIED")
            raise HTTPException(status_code=403, detail="Guarded operations disabled")
        except (ValueError, TypeError):
            audit("CONFIG_SAVE", "INVALID_CONFIG")
            raise HTTPException(status_code=422, detail="Invalid native configuration")
        # Never expose server-side configuration file paths.
        return {"config_id": config_id, "status": "SAVED"}

    @router.post("/api/v1/guarded/jobs", status_code=202)
    def submit_job(payload: dict, authorization: str | None = Header(default=None)):
        authorize(authorization)
        from datetime import datetime
        from crypto_strategy_lab.data_lake_config import (
            ResearchRunConfig, normalize_data_lake_config,
        )
        from crypto_strategy_lab.gui.v2_controller import GuiResearchRequest
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
            raise HTTPException(status_code=422, detail="Invalid request identifier")
        details = payload.get("request")
        config_data = payload.get("config")
        if not isinstance(details, dict) or not isinstance(config_data, dict):
            raise HTTPException(status_code=422, detail="Invalid native job payload")
        required = {"exchange", "market", "symbol", "period_start", "period_end",
                    "strategy_timeframe", "intrabar_timeframe"}
        if set(details) != required:
            raise HTTPException(status_code=422, detail="Invalid native research request")
        try:
            start = datetime.fromisoformat(details["period_start"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(details["period_end"].replace("Z", "+00:00"))
            if not (start.tzinfo and end.tzinfo and start < end):
                raise ValueError("Invalid native request window")
            if details["exchange"] != "binance" or details["market"] not in {"spot", "futures_um"}:
                raise ValueError("Unsupported market")
            symbol = details["symbol"]
            if not isinstance(symbol, str) or not symbol.isascii() or not symbol.isalnum() or not 1 <= len(symbol) <= 32:
                raise ValueError("Invalid symbol")
            if details["strategy_timeframe"] not in {"15m", "1h", "4h", "1d"}:
                raise ValueError("Invalid timeframe")
            if details["intrabar_timeframe"] not in {"1m", "5m", "15m"}:
                raise ValueError("Invalid intrabar timeframe")
            request = GuiResearchRequest(
                exchange="binance", market=details["market"], symbol=symbol.upper(),
                period_start=start, period_end=end,
                strategy_timeframe=details["strategy_timeframe"],
                intrabar_timeframe=details["intrabar_timeframe"],
            )
            config = normalize_data_lake_config(config_data)
            if not isinstance(config, ResearchRunConfig):
                raise ValueError("Native v3 config required")
            config.validate()
        except (ValueError, TypeError, KeyError, AttributeError):
            raise HTTPException(status_code=422, detail="Invalid native job payload")
        try:
            integration.submit(request_id, request, config)
            audit("JOB_SUBMIT", "SUCCESS")
        except PermissionError:
            audit("JOB_SUBMIT", "DENIED")
            raise HTTPException(status_code=403, detail="Guarded operations disabled")
        except (RuntimeError, ValueError):
            audit("JOB_SUBMIT", "REJECTED")
            raise HTTPException(status_code=409, detail="Job submission rejected")
        return {"request_id": request_id, "status": "ACCEPTED"}

    return router
