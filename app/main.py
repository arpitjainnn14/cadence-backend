from fastapi import FastAPI

from app.auth.router import router as auth_router


def create_app() -> FastAPI:
    app = FastAPI(title="Subs")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth_router)
    return app


app = create_app()
