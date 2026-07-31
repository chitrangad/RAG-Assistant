"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse

from src.config import settings
from src.database import init_db, close_db
from src.logging_config import configure_logging, get_logger
from src.middleware.request_id import RequestIDMiddleware
from src.middleware.logging import LoggingMiddleware
from src.middleware.error_handler import ErrorHandlerMiddleware
from src.api.router import api_router
from src.auth import require_admin_page, authenticate_and_login, create_session_token

logger = get_logger(__name__)

TEMPLATES = Path(__file__).parent / "templates"


def _read_template(name: str) -> str:
    """Read a template file, returning its contents. Caches in memory."""
    cache_key = f"_cached_{name}"
    cached = globals().get(cache_key)
    if cached is not None:
        return cached
    path = TEMPLATES / name
    if not path.exists():
        logger.error("template_missing", name=name, path=str(path))
        return f"<html><body><h1>Template {name} not found</h1></body></html>"
    content = path.read_text(encoding="utf-8")
    globals()[cache_key] = content
    return content


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown hooks."""
    configure_logging()
    logger.info("starting", app=settings.app_name, version=settings.app_version)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    await init_db()
    logger.info("database_initialized")
    yield
    await close_db()
    logger.info("shutdown_complete")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(ErrorHandlerMiddleware)
app.add_middleware(LoggingMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
async def root():
    """Evidence-first document search."""
    return HTMLResponse(content=_read_template("search.html"))


@app.get("/admin")
async def admin_page(request: Request):
    """Admin dashboard — manage data sources and ingestion."""
    result = await require_admin_page(request)
    if isinstance(result, RedirectResponse):
        return result
    return HTMLResponse(content=_read_template("admin.html"))


@app.get("/admin/login")
async def admin_login_page(request: Request):
    """Admin login page."""
    return HTMLResponse(content=_read_template("login.html"))


@app.post("/admin/login")
async def admin_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(default="/admin"),
):
    """Process admin login."""
    token = await authenticate_and_login(username, password)
    if token is None:
        template = _read_template("login.html")
        return HTMLResponse(
            content=template.replace(
                'id="login-error" style="display:none"',
                'id="login-error" style="display:block"',
            ),
            status_code=401,
        )

    response = RedirectResponse(url=next, status_code=303)
    response.set_cookie(
        key="admin_session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=28800,  # 8 hours
    )
    return response


@app.get("/api/info")
async def api_info():
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/api/health",
        "query": "/api/chat/query",
        "stats": "/api/ingest/stats",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
