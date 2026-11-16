
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine, Base
from app.api.auth import router as auth_router
from app.api.repositories import router as repositories_router

# Import models so SQLAlchemy knows about all tables
from app.models import User, Repository, Analysis


app = FastAPI(
    title=settings.APP_NAME + " API",
    description="AI-Powered Codebase Intelligence and Developer Assistant",
    version="1.0.0"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip().rstrip("/")
        for origin in settings.CORS_ORIGINS.split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(repositories_router)


@app.on_event("startup")
def create_tables():
    Base.metadata.create_all(bind=engine)


@app.get("/")
def home():
    return {
        "message": "Welcome to CodeMind API!",
        "status": "running"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "message": "CodeMind backend is working"
    }


@app.get("/health/database")
def database_health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return {
            "status": "connected",
            "database": settings.MYSQL_DATABASE
        }

    except Exception:
        return {
            "status": "error",
            "message": "Database connection failed"
        }
