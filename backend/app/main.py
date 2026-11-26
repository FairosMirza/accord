import json
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.errors import DomainError

log = logging.getLogger("accord")
BACKEND_ROOT = Path(__file__).resolve().parent.parent


class JsonFormatter(logging.Formatter):
    """One JSON object per line, which Cloud Logging parses into structured entries."""

    EXTRA = ("request_id", "method", "path", "status", "duration_ms", "user_id")

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
        }
        for key in self.EXTRA:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["stack_trace"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    settings = get_settings()
    handler.setFormatter(JsonFormatter() if settings.environment in ("demo", "production") else logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").disabled = True


def run_migrations() -> None:
    from alembic.config import Config

    from alembic import command
    from app.db import engine

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    with engine.begin() as conn:
        # Several instances may start at once; only one migrates at a time.
        conn.execute(text("SELECT pg_advisory_xact_lock(724002)"))
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.db import SessionLocal
    from app.policy import ensure_policy

    settings = get_settings()
    if settings.run_migrations_on_start:
        run_migrations()
    if settings.demo_mode and settings.seed_demo_data:
        from app.seed import seed_if_empty

        seed_if_empty()
    with SessionLocal() as db:
        ensure_policy(db)
        db.commit()
    log.info("Accord started", extra={"path": settings.environment})
    yield


def _static_dir() -> Path:
    import os

    configured = os.environ.get("ACCORD_STATIC_DIR")
    return Path(configured) if configured else BACKEND_ROOT.parent / "frontend" / "dist"


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    app = FastAPI(
        title=settings.app_name,
        description="Spend approvals for Orvane Group",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError):
        return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        errors = exc.errors()
        first = errors[0] if errors else {}
        field = ".".join(str(p) for p in first.get("loc", [])[1:]) or "request"
        return JSONResponse({"detail": f"Please check {field}: {first.get('msg', 'invalid value')}", "code": "validation", "errors": json.loads(json.dumps(errors, default=str))}, status_code=422)

    base_origin = "{0.scheme}://{0.netloc}".format(urlparse(settings.base_url))

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # CSRF: state-changing API calls must come from our own pages. Browsers can't add a
        # custom header cross-site without a CORS preflight, which we never allow.
        path = request.url.path
        if request.method not in ("GET", "HEAD", "OPTIONS") and path.startswith("/api/"):
            origin = request.headers.get("origin")
            if request.headers.get("x-requested-with") != "accord" or (origin and origin != base_origin and origin != f"{request.url.scheme}://{request.url.netloc}"):
                return JSONResponse({"detail": "Request blocked.", "code": "csrf"}, status_code=403)
        request_id = request.headers.get("x-cloud-trace-context", "").split("/")[0] or uuid.uuid4().hex[:16]
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("Unhandled error", extra={"request_id": request_id, "method": request.method, "path": path})
            response = JSONResponse({"detail": "Something went wrong on our side. Please try again.", "code": "server_error"}, status_code=500)
        duration = round((time.perf_counter() - started) * 1000, 1)
        if path not in ("/api/health",):
            log.info(f"{request.method} {path} {response.status_code}", extra={"request_id": request_id, "method": request.method, "path": path, "status": response.status_code, "duration_ms": duration})
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Permissions-Policy", "geolocation=(), microphone=(), payment=()")
        h.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
            "script-src 'self'; connect-src 'self'; frame-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'",
        )
        if settings.cookie_secure:
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if path.startswith("/assets/"):
            h["Cache-Control"] = "public, max-age=31536000, immutable"
        elif path.startswith("/api/") and "cache-control" not in h:
            h["Cache-Control"] = "no-store"
        h["X-Request-Id"] = request_id
        return response

    # Only used to carry OIDC state/nonce across the sign-in redirect.
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, session_cookie="accord_sso", max_age=600, same_site="lax", https_only=settings.cookie_secure)

    from app.api import admin, app_routes, auth, requests, system

    app.include_router(auth.router)
    app.include_router(requests.router)
    app.include_router(app_routes.router)
    app.include_router(admin.router)
    app.include_router(system.demo_router)
    app.include_router(system.jobs_router)

    # Cloud Run reserves paths ending in "z" (e.g. /healthz), so health checks live under /api.
    @app.get("/api/health", include_in_schema=False)
    def health():
        return {"ok": True}

    @app.get("/api/ready", include_in_schema=False)
    def ready():
        from app.db import engine

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True}

    static = _static_dir()
    if (static / "index.html").exists():
        if (static / "assets").exists():
            app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
        def spa(full_path: str):
            if full_path.startswith(("api/", "internal/")):
                raise HTTPException(404, "Not found.")
            candidate = (static / full_path).resolve()
            if full_path and candidate.is_file() and static.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
