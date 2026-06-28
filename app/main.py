from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes import auth, intake, patient
from app.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager — runs setup before the server starts accepting
    requests and teardown after it stops.

    The modern FastAPI approach (replaces deprecated @app.on_event).
    """
    print(f"\n🏥  {settings.app_name} v{settings.app_version} — starting up")
    print(f"📖  API docs available at: http://localhost:8000/docs\n")
    yield
    print(f"\n🏥  {settings.app_name} — shutting down gracefully\n")


# ── FastAPI App ────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Intelligent Patient Triage & Symptom Routing API. "
        "An AI-powered intake layer that classifies urgency, routes patients "
        "to the right specialist, and notifies doctors — asynchronously."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── Middleware ─────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # Tighten to specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
API_PREFIX = "/api/v1"

app.include_router(auth.router,    prefix=API_PREFIX)
app.include_router(patient.router, prefix=API_PREFIX)
app.include_router(intake.router,  prefix=API_PREFIX)


# ── Health Endpoints ───────────────────────────────────────────────────────────
@app.get("/", tags=["Health"], summary="Root")
def root():
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "status": "operational",
        "docs": "/docs",
        "redoc": "/redoc",
    }


@app.get("/health", tags=["Health"], summary="Health check")
def health_check():
    """Simple liveness probe — used by Docker and load balancers."""
    return {"status": "healthy"}
