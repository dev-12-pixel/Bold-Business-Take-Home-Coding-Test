from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db import migrate, owner_engine
from app.recruiters import seed_recruiters


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    engine = owner_engine()
    migrate(engine)
    seed_recruiters(engine, get_settings().recruiters_csv)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="TechForce", lifespan=lifespan)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
