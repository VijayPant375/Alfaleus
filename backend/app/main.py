"""
Alfaleus Backend — FastAPI Application Entry Point

Initialises the app, registers middleware, mounts routers, and exposes
the /health endpoint. Full routes are added in later phases.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import jobs, candidates

app = FastAPI(
    title="Alfaleus",
    description="AI-Powered Talent Screening Platform",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(jobs.router)
app.include_router(candidates.router)

# ---------------------------------------------------------------------------
# Core endpoints
# ---------------------------------------------------------------------------


@app.get("/health", tags=["system"], summary="Health check")
async def health() -> dict:
    """Returns service status. Used by load balancers and Docker health checks."""
    return {"status": "ok", "service": "alfaleus-backend"}
