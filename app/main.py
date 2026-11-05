import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.auth.csrf import CSRFMiddleware
from app.auth.router import router as auth_router
from app.core.config import Settings, get_settings
from app.core.docs import router as docs_router
from app.core.health import HealthRepo
from app.insights.router import router as insights_router
from app.payment_methods.router import router as payment_methods_router
from app.reminders.router import internal_router, router as push_router
from app.subscriptions.router import merchants_router, router as subscriptions_router

logger = logging.getLogger("app.health")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    # Built-in docs are off everywhere; app.core.docs serves them under /api, behind login.
    app = FastAPI(title="Cadence", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/health/db")
    def health_db(repo: HealthRepo) -> JSONResponse:
        try:
            repo.ping()
        except Exception:
            logger.exception("db health check failed")
            repo.reset()  # a failed query leaves the transaction aborted; don't let get_db's commit fail
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ok"})

    app.add_middleware(CSRFMiddleware)
    app.include_router(docs_router)
    app.include_router(auth_router)
    app.include_router(payment_methods_router)
    app.include_router(subscriptions_router)
    app.include_router(merchants_router)
    app.include_router(insights_router)
    app.include_router(push_router)
    app.include_router(internal_router)
    return app


app = create_app()
