import logging

from fastapi import FastAPI
from sqlalchemy import inspect

from app.core.db import engine, Base
from app.models import Job, Transaction, JobSummary, MerchantCategoryCache  # noqa: F401 - register models
from app.api.routes import router

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Artha Transaction Processing Pipeline",
    description="AI-powered, async CSV transaction cleaning, anomaly detection and classification pipeline.",
    version="1.0.0",
)


@app.on_event("startup")
def on_startup():
    # Simple create_all for assignment scope; in production this would be
    # replaced entirely by Alembic migrations (see README "Next iteration").
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(router)
