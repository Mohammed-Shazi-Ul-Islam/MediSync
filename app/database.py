from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings

settings = get_settings()

# ── SQLAlchemy Engine ──────────────────────────────────────────────────────────
# pool_pre_ping=True: Tests connection health before handing it from pool
# pool_size: Max persistent connections kept open
# max_overflow: Extra connections allowed beyond pool_size during spikes
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=settings.debug,  # Logs SQL queries when DEBUG=true
)

# ── Session Factory ────────────────────────────────────────────────────────────
# autocommit=False: We control transactions explicitly
# autoflush=False: We control when to flush to DB
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ── Declarative Base ───────────────────────────────────────────────────────────
# All SQLAlchemy ORM models inherit from this Base.
# It registers them in Base.metadata, which Alembic uses to generate migrations.
class Base(DeclarativeBase):
    pass


# ── Dependency ─────────────────────────────────────────────────────────────────
def get_db():
    """
    FastAPI dependency that provides a DB session per request.
    Uses a generator with try/finally to guarantee the session is always closed,
    even if an exception is raised during the request.

    Usage in routes:
        @router.get("/example")
        def example(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
