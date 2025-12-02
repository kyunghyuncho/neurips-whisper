"""
Database Connection and Session Management

This module sets up SQLAlchemy's async database engine and provides
a dependency injection function for FastAPI routes to access database sessions.
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.config import settings


# Create async database engine
# - echo=True: Logs all SQL statements (useful for debugging but verbose)
# - Uses asyncpg driver for PostgreSQL (specified in DATABASE_URL)
# - Connection pool is automatically managed by SQLAlchemy
engine = create_async_engine(settings.DATABASE_URL, echo=False)


# Session factory for creating database sessions
# - class_=AsyncSession: Creates async-compatible sessions
# - expire_on_commit=False: Prevents objects from becoming stale after commit
#   This is important because we often need to access object attributes after
#   committing, and with async code we can't make blocking calls to refresh them
AsyncSessionLocal = sessionmaker(
    engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)


async def get_db():
    """
    Database session dependency for FastAPI routes.
    
    This is a generator function that yields a database session
    and automatically handles cleanup when the request is complete.
    
    Usage in FastAPI routes:
        @app.get("/endpoint")
        async def route(db: AsyncSession = Depends(get_db)):
            # Use db here
            result = await db.execute(select(User))
    
    The async context manager ensures the session is properly closed
    even if an exception occurs during request handling.
    """
    async with AsyncSessionLocal() as session:
        yield session
