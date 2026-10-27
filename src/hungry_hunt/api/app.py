"""Review API application factory; `app` is what uvicorn serves."""

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hungry_hunt.api.deps import Context
from hungry_hunt.api.routes import companies, coverage, digest, health, jobs, outreach
from hungry_hunt.config import Settings
from hungry_hunt.db import make_engine, session_factory
from hungry_hunt.log import configure_logging


def create_app(
    settings: Settings | None = None, sf=None, now: Callable[[], datetime] = lambda: datetime.now(UTC), llm=None
) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level, settings.log_format)
    app = FastAPI(title="Hungry Hunt API", version="0.1.0")
    app.state.ctx = Context(settings, sf or session_factory(make_engine(settings.database_url)), now, llm)
    app.add_middleware(
        CORSMiddleware, allow_origins=[settings.review_base_url.rstrip("/")], allow_methods=["*"], allow_headers=["*"]
    )
    for r in (health, digest, jobs, outreach, companies, coverage):
        app.include_router(r.router)
    return app


app = create_app()
