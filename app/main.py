from fastapi import FastAPI

from app.auth.csrf import CSRFMiddleware
from app.auth.router import router as auth_router
from app.payment_methods.router import router as payment_methods_router


def create_app() -> FastAPI:
    app = FastAPI(title="Subs")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(CSRFMiddleware)
    app.include_router(auth_router)
    app.include_router(payment_methods_router)
    return app


app = create_app()
