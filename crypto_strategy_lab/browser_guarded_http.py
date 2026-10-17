"""Opt-in HTTP router for guarded job inspection. Not installed by production launcher.

The existing browser_http local-origin middleware must wrap any application
that includes this router. This router additionally authenticates every call.
"""
from __future__ import annotations

import secrets


def create_guarded_job_router(*, token: str, integration, enabled: bool = False):
    from fastapi import APIRouter, Header, HTTPException
    router = APIRouter()
    if enabled is not True:
        return router
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("A browser bearer token is required")

    def authorize(authorization: str | None):
        supplied = authorization.removeprefix("Bearer ") if authorization else ""
        if not secrets.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="Unauthorized")

    def invoke(call):
        try:
            return call()
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown job")
        except PermissionError:
            raise HTTPException(status_code=403, detail="Guarded operations disabled")

    @router.get("/api/v1/guarded/jobs/{request_id}")
    def status(request_id: str, authorization: str | None = Header(default=None)):
        authorize(authorization)
        return invoke(lambda: integration.status(request_id))

    @router.get("/api/v1/guarded/jobs/{request_id}/progress")
    def progress(request_id: str, authorization: str | None = Header(default=None)):
        authorize(authorization)
        return invoke(lambda: integration.progress(request_id))

    @router.post("/api/v1/guarded/jobs/{request_id}/cancel")
    def cancel(request_id: str, authorization: str | None = Header(default=None)):
        authorize(authorization)
        return invoke(lambda: integration.cancel(request_id))

    return router
