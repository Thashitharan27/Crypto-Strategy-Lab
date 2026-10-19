"""Optional local read-only HTTP adapter.

Never imported by the backtest engine or live bot. Installation of FastAPI is
optional; application construction exposes no trading or filesystem endpoints.
"""
import secrets
import math
from numbers import Integral, Real
from contextlib import asynccontextmanager
from urllib.parse import urlsplit


def _json_safe_summary(value):
    """Make non-finite summary metrics JSON-safe without changing stored results."""
    if isinstance(value, dict):
        return {key: _json_safe_summary(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_summary(item) for item in value]
    if isinstance(value, Integral) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, Real) and not isinstance(value, bool):
        number = float(value)
        if not math.isfinite(number):
            if math.isnan(number):
                return None  # Undefined statistic (for example, no losing trades).
            return "Infinity" if number > 0 else "-Infinity"
        return number
    return value


def create_browser_app(*, token: str, read_service=None, completed_run_root=None, config_root=None, static_root=None, visualizer_coordinator=None, guarded_integration=None, guarded_enabled=False, guarded_audit_callback=None, guarded_require_audit_admission=False):
    """Construct an authenticated app; caller must bind server to 127.0.0.1."""
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("A fresh, high-entropy browser token is required")
    from fastapi import FastAPI, Header, HTTPException, Request
    from starlette.responses import JSONResponse

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            try:
                if guarded_enabled is True and guarded_integration is not None:
                    guarded_integration.close()
            finally:
                if visualizer_coordinator is not None:
                    visualizer_coordinator.stop()

    app = FastAPI(title="Crypto Strategy Lab (read-only)", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    # Only an explicit non-production composition may attach guarded routes.
    # browser_launcher intentionally passes neither argument.
    if guarded_enabled is True:
        if guarded_integration is None:
            raise ValueError("Guarded integration is required for opt-in composition")
        from crypto_strategy_lab.browser_guarded_http import create_guarded_job_router
        app.include_router(create_guarded_job_router(
            token=token, integration=guarded_integration, enabled=True,
            audit_callback=guarded_audit_callback,
            require_audit_admission=guarded_require_audit_admission,
        ))

    @app.middleware("http")
    async def local_guard(request: Request, call_next):
        host = request.headers.get("host", "")
        origin = request.headers.get("origin")
        try:
            parsed_host = urlsplit("http://" + host)
            valid_host = (
                parsed_host.hostname in {"127.0.0.1", "localhost"}
                and (parsed_host.port is None or 1 <= parsed_host.port <= 65535)
                and not host.endswith(":")
                and parsed_host.username is None
                and parsed_host.password is None
                and parsed_host.path == ""
                and parsed_host.query == ""
                and parsed_host.fragment == ""
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
        # Guarded endpoints may change native state. A different localhost
        # port is a different browser origin, even if both are loopback.
        # Preserve no-Origin CLI/TestClient requests; bearer auth remains
        # mandatory inside every guarded route.
        if ((request.url.path == "/api/v1/guarded/jobs" or
                 request.url.path.startswith("/api/v1/guarded/"))
                and origin is not None
                and origin != "http://" + host):
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
        return await call_next(request)

    @app.get("/api/v1/health")
    def health(authorization: str | None = Header(default=None)):
        supplied = authorization.removeprefix("Bearer ") if authorization else ""
        if not secrets.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="Unauthorized")
        return {"status": "ok", "mode": "read-only"}

    @app.get("/api/v1/release/capabilities")
    def release_capabilities(authorization: str | None = Header(default=None)):
        """B4 server-owned release contract; no caller/environment can enable it.

        A future activation requires a separate approved composition change.
        Advertising false never constructs a guarded integration or adds routes.
        """
        supplied = authorization.removeprefix("Bearer ") if authorization else ""
        if not secrets.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="Unauthorized")
        return {"execution": False, "configuration_editing": False}

    if read_service is not None:
        @app.get("/api/v1/capabilities")
        def capabilities(authorization: str | None = Header(default=None)):
            supplied = authorization.removeprefix("Bearer ") if authorization else ""
            if not secrets.compare_digest(supplied, token):
                raise HTTPException(status_code=401, detail="Unauthorized")
            return read_service.capabilities()

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

    if read_service is not None and completed_run_root is not None:
        @app.get("/api/v1/portfolio/candidates")
        def portfolio_candidates(authorization: str | None = Header(default=None)):
            from pathlib import Path
            supplied = authorization.removeprefix("Bearer ") if authorization else ""
            if not secrets.compare_digest(supplied, token):
                raise HTTPException(status_code=401, detail="Unauthorized")
            root = Path(completed_run_root).resolve()
            if not root.is_dir():
                return {"candidates": []}
            try:
                rows = read_service.portfolio_candidates(root)
            except (OSError, ValueError, KeyError, TypeError):
                raise HTTPException(status_code=503, detail="Portfolio discovery unavailable")
            return {"candidates": rows[:100]}

    if read_service is not None and completed_run_root is not None:
        @app.get("/api/v1/runs/{run_id}")
        def completed_run(run_id: str, authorization: str | None = Header(default=None)):
            from pathlib import Path
            supplied = authorization.removeprefix("Bearer ") if authorization else ""
            if not secrets.compare_digest(supplied, token):
                raise HTTPException(status_code=401, detail="Unauthorized")
            if not (1 <= len(run_id) <= 100 and run_id.isascii() and
                    all(c.isalnum() or c in "_-" for c in run_id)):
                raise HTTPException(status_code=404, detail="Run not found")
            root = Path(completed_run_root).resolve()
            candidate = root / run_id
            if candidate.is_symlink():
                raise HTTPException(status_code=404, detail="Run not found")
            target = candidate.resolve()
            if target.parent != root or not target.is_dir():
                raise HTTPException(status_code=404, detail="Run not found")
            try:
                result = read_service.completed_run(target)
                summary = result.get("summary", {})
                if isinstance(summary, dict):
                    # Pandas statistics legitimately use NaN for undefined groups.
                    # The API must still return strict JSON to the browser.
                    result = {**result, "summary": _json_safe_summary(summary)}
                return result
            except (OSError, ValueError, KeyError, TypeError):
                raise HTTPException(status_code=404, detail="Run not found")

    if read_service is not None and config_root is not None:
        @app.get("/api/v1/configs/{config_id}")
        def research_config(config_id: str, authorization: str | None = Header(default=None)):
            from pathlib import Path
            supplied = authorization.removeprefix("Bearer ") if authorization else ""
            if not secrets.compare_digest(supplied, token):
                raise HTTPException(status_code=401, detail="Unauthorized")
            if not (1 <= len(config_id) <= 100 and config_id.isascii() and
                    all(c.isalnum() or c in "_-" for c in config_id)):
                raise HTTPException(status_code=404, detail="Configuration not found")
            root = Path(config_root).resolve()
            candidate = root / (config_id + ".json")
            if candidate.is_symlink():
                raise HTTPException(status_code=404, detail="Configuration not found")
            target = candidate.resolve()
            if target.parent != root or not target.is_file():
                raise HTTPException(status_code=404, detail="Configuration not found")
            try:
                return {"config": read_service.research_config(target)}
            except (OSError, ValueError, KeyError, TypeError):
                raise HTTPException(status_code=404, detail="Configuration not found")

    if visualizer_coordinator is not None:
        @app.post("/api/v1/visualizer/sessions/{run_id}", status_code=201)
        def open_visualizer_session(run_id: str, request: Request, authorization: str | None = Header(default=None)):
            # A session launch is an explicit in-memory user action, never a
            # GET or a background page load. Enforce same-origin beyond bearer.
            supplied = authorization.removeprefix("Bearer ") if authorization else ""
            if not secrets.compare_digest(supplied, token):
                raise HTTPException(status_code=401, detail="Unauthorized")
            if not (1 <= len(run_id) <= 100 and run_id.isascii() and
                    all(char.isalnum() or char in "_-" for char in run_id)):
                raise HTTPException(status_code=404, detail="Completed run unavailable")
            origin = request.headers.get("origin")
            if not origin or origin != f"http://{request.headers.get('host', '')}":
                raise HTTPException(status_code=403, detail="Same-origin launch required")
            if request.headers.get("sec-fetch-site", "same-origin") != "same-origin":
                raise HTTPException(status_code=403, detail="Cross-site launch forbidden")
            try:
                url = visualizer_coordinator.open_completed_run(run_id)
            except (OSError, ValueError, KeyError, TypeError):
                raise HTTPException(status_code=404, detail="Completed run unavailable")
            return {"url": url}


    if static_root is not None:
        from pathlib import Path
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
        root = Path(static_root).resolve()
        if not root.is_dir() or not (root / "index.html").is_file():
            raise ValueError("Browser distribution is missing index.html")
        assets = root / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="browser-assets")

        @app.get("/", include_in_schema=False)
        def browser_index():
            return FileResponse(root / "index.html", media_type="text/html",
                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    return app
