"""Optional local read-only HTTP adapter.

Never imported by the backtest engine or live bot. Installation of FastAPI is
optional; application construction exposes no trading or filesystem endpoints.
"""
from __future__ import annotations

import secrets
from urllib.parse import urlsplit


def create_browser_app(*, token: str, read_service=None):
    """Construct an authenticated app; caller must bind server to 127.0.0.1."""
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("A fresh, high-entropy browser token is required")
    from fastapi import FastAPI, Header, HTTPException, Request
    from starlette.responses import JSONResponse

    app = FastAPI(title="Crypto Strategy Lab (read-only)", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def local_guard(request: Request, call_next):
        host = request.headers.get("host", "")
        origin = request.headers.get("origin")
        try:
            parsed_host = urlsplit("http://" + host)
            valid_host = (
                parsed_host.hostname in {"127.0.0.1", "localhost"}
                and parsed_host.username is None
                and parsed_host.password is None
                and parsed_host.path == ""
                and parsed_host.query == ""
            )
            if origin is None:
                valid_origin = True
            else:
                parsed_origin = urlsplit(origin)
                valid_origin = (
                    parsed_origin.scheme == "http"
                    and parsed_origin.hostname in {"127.0.0.1", "localhost"}
                    and parsed_origin.username is None
                    and parsed_origin.password is None
                    and parsed_origin.path in {"", "/"}
                    and parsed_origin.query == ""
                    and parsed_origin.fragment == ""
                    and parsed_origin.port is not None
                )
        except ValueError:
            valid_host, valid_origin = False, False
        if not valid_host or not valid_origin:
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
        return await call_next(request)

    @app.get("/api/v1/health")
    def health(authorization: str | None = Header(default=None)):
        supplied = authorization.removeprefix("Bearer ") if authorization else ""
        if not secrets.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="Unauthorized")
        return {"status": "ok", "mode": "read-only"}

    if read_service is not None:
        @app.get("/api/v1/catalog/symbols")
        def symbols(authorization: str | None = Header(default=None), market: str = "futures_um"):
            supplied = authorization.removeprefix("Bearer ") if authorization else ""
            if not secrets.compare_digest(supplied, token):
                raise HTTPException(status_code=401, detail="Unauthorized")
            if market not in {"futures_um", "spot"}:
                raise HTTPException(status_code=422, detail="Unsupported market")
            return {"symbols": read_service.symbols(market)}

    if read_service is not None:
        @app.get("/api/v1/catalog/coverage")
        def coverage(authorization: str | None = Header(default=None), symbol: str = "", market: str = "futures_um",
                     start: str = "", end: str = "", strategy_timeframe: str = "4h", intrabar_timeframe: str = "1m"):
            import datetime
            from crypto_strategy_lab.gui.v2_controller import GuiResearchRequest
            supplied = authorization.removeprefix("Bearer ") if authorization else ""
            if not secrets.compare_digest(supplied, token):
                raise HTTPException(status_code=401, detail="Unauthorized")
            if market not in {"futures_um", "spot"} or not symbol.isascii() or not symbol.isalnum() or len(symbol) > 32:
                raise HTTPException(status_code=422, detail="Invalid market or symbol")
            if strategy_timeframe not in {"15m", "1h", "4h", "1d"} or intrabar_timeframe not in {"1m", "5m", "15m"}:
                raise HTTPException(status_code=422, detail="Unsupported timeframes")
            try:
                start_date = datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))
                end_date = datetime.datetime.fromisoformat(end.replace("Z", "+00:00"))
                if not (start_date.tzinfo and end_date.tzinfo and start_date < end_date):
                    raise ValueError()
                request = GuiResearchRequest(exchange="binance", market=market, symbol=symbol.upper(),
                    period_start=start_date, period_end=end_date, strategy_timeframe=strategy_timeframe,
                    intrabar_timeframe=intrabar_timeframe)
            except (ValueError, TypeError):
                raise HTTPException(status_code=422, detail="Invalid research time window")
            return {"coverage": read_service.coverage(request)}

    return app
