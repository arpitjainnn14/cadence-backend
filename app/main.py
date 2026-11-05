from fastapi import FastAPI

from app.auth.csrf import CSRFMiddleware
from app.auth.router import router as auth_router
from app.core.config import Settings, get_settings
from app.insights.router import router as insights_router
from app.payment_methods.router import router as payment_methods_router
from app.reminders.router import internal_router, router as push_router
from app.subscriptions.router import merchants_router, router as subscriptions_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    # cookie_secure means production: don't publish the API schema or interactive docs there.
    docs = {"docs_url": None, "redoc_url": None, "openapi_url": None} if settings.cookie_secure else {}
    app = FastAPI(title="Cadence", **docs)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(CSRFMiddleware)
    app.include_router(auth_router)
    app.include_router(payment_methods_router)
    app.include_router(subscriptions_router)
    app.include_router(merchants_router)
    app.include_router(insights_router)
    app.include_router(push_router)
    app.include_router(internal_router)
    return app


app = create_app()
