"""Optional local read-only HTTP adapter.

Never imported by the backtest engine or live bot. Installation of FastAPI is
optional; application construction exposes no trading or filesystem endpoints.
"""
from __future__ import annotations

import secrets


def create_browser_app(*, token: str):
    """Construct an authenticated app; caller must bind server to 127.0.0.1."""
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("A fresh, high-entropy browser token is required")
    from fastapi import FastAPI, Header, HTTPException, Request

    app = FastAPI(title="Crypto Strategy Lab (read-only)", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def local_guard(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0].lower()
        origin = request.headers.get("origin")
        if host not in {"127.0.0.1", "localhost"}:
            raise HTTPException(status_code=403, detail="Invalid Host")
        if origin is not None and origin.rstrip("/") not in {"http://127.0.0.1", "http://localhost"} and not (
            origin.startswith("http://127.0.0.1:") or origin.startswith("http://localhost:")
        ):
            raise HTTPException(status_code=403, detail="Invalid Origin")
        return await call_next(request)

    @app.get("/api/v1/health")
    def health(authorization: str | None = Header(default=None)):
        supplied = authorization.removeprefix("Bearer ") if authorization else ""
        if not secrets.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="Unauthorized")
        return {"status": "ok", "mode": "read-only"}

    return app
