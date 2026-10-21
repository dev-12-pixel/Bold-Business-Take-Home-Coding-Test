from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="TechForce")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
