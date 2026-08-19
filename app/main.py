import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes import auth, intake, patient, routing, doctor
from app.api.v1.routes import admin  # Module 06
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager — runs setup before the server starts accepting
    requests and teardown after it stops.

    The modern FastAPI approach (replaces deprecated @app.on_event).

    Module 02: Seeds the ChromaDB medical knowledge base on startup.
    Runs in a thread-pool executor to avoid blocking the async event loop
    (ChromaDB and the Google Embeddings API are synchronous).
    """
    print(f"\n🏥  {settings.app_name} v{settings.app_version} — starting up")
    print(f"📖  API docs available at: http://localhost:8000/docs\n")

    # ── Module 02: Seed ChromaDB medical knowledge base ───────────────────────
    if settings.gemini_api_key:
        try:
            from app.services.triage_service import triage_service
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, triage_service.seed_knowledge_base)
            print("🦷  ChromaDB medical knowledge base ready\n")
        except Exception as e:
            logger.error(f"[STARTUP] ChromaDB seed failed (non-fatal): {e}")
            print(f"⚠️  ChromaDB seed failed: {e}\n")

        # ── Module 03: Seed specialist profiles collection ─────────────────
        try:
            from app.services.specialist_router import hybrid_router
            await loop.run_in_executor(None, hybrid_router.seed_specialist_profiles)
            print("🏥  ChromaDB specialist profiles ready\n")
        except Exception as e:
            logger.error(f"[STARTUP] Specialist profile seed failed (non-fatal): {e}")
            print(f"⚠️  Specialist profile seed failed: {e}\n")
    else:
        print("⚠️  GEMINI_API_KEY not set — AI triage and routing will be disabled\n")
    # ────────────────────────────────────────────────────────────────────────────────────────────────

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

# ── Module 06: Rate Limiting ───────────────────────────────────────────────────
from app.middleware.rate_limiter import limiter, get_rate_limit_exceeded_handler

app.state.limiter = limiter
exc_class, exc_handler = get_rate_limit_exceeded_handler()
app.add_exception_handler(exc_class, exc_handler)

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
app.include_router(routing.router, prefix=API_PREFIX)
app.include_router(doctor.router,  prefix=API_PREFIX)  # Module 05 — Doctor Dashboard
app.include_router(admin.router,   prefix=API_PREFIX)  # Module 06 — Admin + Audit Layer


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

