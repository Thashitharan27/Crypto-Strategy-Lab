"""Opt-in HTTP router for guarded job inspection. Not installed by production launcher.

The existing browser_http local-origin middleware must wrap any application
that includes this router. This router additionally authenticates every call.
"""
from __future__ import annotations

import secrets
import re
import json

# Limit pre-schema materialization of opt-in guarded native configuration bodies.
_MAX_GUARDED_JSON_BYTES = 4 * 1024 * 1024
from starlette.requests import Request

_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")


def create_guarded_job_router(*, token: str, integration, enabled: bool = False, audit_callback=None, require_audit_admission: bool = False):
    from fastapi import APIRouter, Header, HTTPException
    router = APIRouter()
    if enabled is not True:
        return router
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("A browser bearer token is required")

    audit_broken = False

    def audit(operation: str, outcome: str) -> bool:
        nonlocal audit_broken
        # Never log IDs, payloads, tokens, result data or native exception text.
        if audit_callback is not None:
            try:
                audit_callback({"operation": operation, "outcome": outcome})
                return True
            except Exception:
                # An operation may already have committed; never claim that it
                # was rolled back. Deny all subsequent mutations in this app.
                if require_audit_admission is True:
                    audit_broken = True
                return False
        return not require_audit_admission


    def admit_mutation(operation: str) -> None:
        nonlocal audit_broken
        # A durable ATTEMPT record must precede any native mutation in the B4
        # candidate. Do not treat later audit failures as rollback evidence.
        if require_audit_admission is not True:
            return
        if audit_broken:
            raise HTTPException(status_code=503, detail="Guarded audit unavailable")
        try:
            if not callable(audit_callback):
                raise RuntimeError("B4 audit callback missing")
            audit_callback({"operation": operation, "outcome": "ATTEMPT"})
        except Exception:
            audit_broken = True
            # Never leak filesystem, credentials or native error text.
            raise HTTPException(status_code=503, detail="Guarded audit unavailable")

    def authorize(authorization: str | None):
        supplied = authorization[len("Bearer "):] if authorization and authorization.startswith("Bearer ") else ""
        if not secrets.compare_digest(supplied, token):
            audit("AUTH", "DENIED")
            raise HTTPException(status_code=401, detail="Unauthorized")

    def invoke(request_id, call, operation):
        if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
            audit(operation, "INVALID_ID")
            raise HTTPException(status_code=404, detail="Unknown job")
        try:
            result = call()
            if not audit(operation, "SUCCESS") and require_audit_admission:
                raise HTTPException(status_code=503, detail="Guarded outcome unverified")
            return result
        except KeyError:
            audit(operation, "NOT_FOUND")
            raise HTTPException(status_code=404, detail="Unknown job")
        except PermissionError:
            audit(operation, "DENIED")
            raise HTTPException(status_code=403, detail="Guarded operations disabled")
        except (OSError, RuntimeError):
            audit(operation, "UNAVAILABLE")
            raise HTTPException(status_code=503, detail="Guarded job service unavailable")

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
        admit_mutation("CANCEL")
        return invoke(request_id, lambda: integration.cancel(request_id), "CANCEL")

    async def authenticated_json_object(request: Request, authorization: str | None, operation: str):
        # FastAPI's typed body validation runs before endpoint authorization.
        # Explicitly authenticate first, then parse only for authorized callers.
        authorize(authorization)
        # Authenticate before consuming any body. Neither Content-Length nor
        # client-side UI limits are trusted as the sole protection: streaming
        # requests may omit or lie about their declared byte count.
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                declared_size = int(declared)
            except ValueError:
                audit(operation, "INVALID_INPUT")
                raise HTTPException(status_code=422, detail="Invalid request length")
            if declared_size < 0:
                audit(operation, "INVALID_INPUT")
                raise HTTPException(status_code=422, detail="Invalid request length")
            if declared_size > _MAX_GUARDED_JSON_BYTES:
                audit(operation, "OVERSIZED")
                raise HTTPException(status_code=413, detail="Guarded JSON payload too large")
        raw = bytearray()
        try:
            async for chunk in request.stream():
                if len(raw) + len(chunk) > _MAX_GUARDED_JSON_BYTES:
                    audit(operation, "OVERSIZED")
                    raise HTTPException(status_code=413, detail="Guarded JSON payload too large")
                raw.extend(chunk)
            payload = json.loads(raw)
        except HTTPException:
            raise
        except (ValueError, UnicodeError, RuntimeError):
            audit(operation, "INVALID_INPUT")
            raise HTTPException(status_code=422, detail="Invalid JSON payload")
        if not isinstance(payload, dict):
            audit(operation, "INVALID_INPUT")
            raise HTTPException(status_code=422, detail="Invalid JSON object")
        return payload

    @router.put("/api/v1/guarded/configs/{config_id}")
    async def save_config(config_id: str, request: Request, authorization: str | None = Header(default=None)):
        payload = await authenticated_json_object(request, authorization, "CONFIG_SAVE")
        if not isinstance(config_id, str) or _REQUEST_ID.fullmatch(config_id) is None:
            audit("CONFIG_SAVE", "INVALID_ID")
            raise HTTPException(status_code=404, detail="Unknown configuration")
        admit_mutation("CONFIG_SAVE")
        try:
            integration.save_config(config_id, payload)
            if not audit("CONFIG_SAVE", "SUCCESS") and require_audit_admission:
                raise HTTPException(status_code=503, detail="Guarded outcome unverified")
        except PermissionError as exc:
            # Capability denial uses a plain PermissionError. A native OS
            # permission/sharing error carries errno and is a persistence
            # failure, not evidence that the guarded capability is disabled.
            if exc.errno is not None:
                audit("CONFIG_SAVE", "PERSISTENCE_FAILED")
                raise HTTPException(status_code=503, detail="Configuration persistence unavailable")
            audit("CONFIG_SAVE", "DENIED")
            raise HTTPException(status_code=403, detail="Guarded operations disabled")
        except (ValueError, TypeError):
            audit("CONFIG_SAVE", "INVALID_CONFIG")
            raise HTTPException(status_code=422, detail="Invalid native configuration")
        except (OSError, RuntimeError):
            # Native failures can include private paths; never echo them.
            audit("CONFIG_SAVE", "PERSISTENCE_FAILED")
            raise HTTPException(status_code=503, detail="Configuration persistence unavailable")
        # Never expose server-side configuration file paths.
        return {"config_id": config_id, "status": "SAVED"}

    @router.post("/api/v1/guarded/jobs", status_code=202)
    async def submit_job(request: Request, authorization: str | None = Header(default=None)):
        payload = await authenticated_json_object(request, authorization, "JOB_SUBMIT")
        from datetime import datetime
        from crypto_strategy_lab.data_lake_config import (
            ResearchRunConfig, normalize_data_lake_config,
        )
        from crypto_strategy_lab.gui.v2_controller import GuiResearchRequest
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
            audit("JOB_SUBMIT", "INVALID_INPUT")
            raise HTTPException(status_code=422, detail="Invalid request identifier")
        details = payload.get("request")
        config_data = payload.get("config")
        if not isinstance(details, dict) or not isinstance(config_data, dict):
            audit("JOB_SUBMIT", "INVALID_INPUT")
            raise HTTPException(status_code=422, detail="Invalid native job payload")
        required = {"exchange", "market", "symbol", "period_start", "period_end",
                    "strategy_timeframe", "intrabar_timeframe"}
        if set(details) != required:
            audit("JOB_SUBMIT", "INVALID_INPUT")
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
            audit("JOB_SUBMIT", "INVALID_INPUT")
            raise HTTPException(status_code=422, detail="Invalid native job payload")
        admit_mutation("JOB_SUBMIT")
        try:
            integration.submit(request_id, request, config)
            if not audit("JOB_SUBMIT", "SUCCESS") and require_audit_admission:
                raise HTTPException(status_code=503, detail="Guarded outcome unverified")
        except PermissionError:
            audit("JOB_SUBMIT", "DENIED")
            raise HTTPException(status_code=403, detail="Guarded operations disabled")
        except (RuntimeError, ValueError):
            audit("JOB_SUBMIT", "REJECTED")
            raise HTTPException(status_code=409, detail="Job submission rejected")
        except OSError:
            audit("JOB_SUBMIT", "EXECUTION_UNAVAILABLE")
            raise HTTPException(status_code=503, detail="Native research service unavailable")
        return {"request_id": request_id, "status": "ACCEPTED"}

    return router
