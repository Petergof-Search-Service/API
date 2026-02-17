from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# Create async engine
engine = create_async_engine(
    str(settings.DATABASE_URL),
    pool_pre_ping=True,  # Проверять соединение перед использованием
    pool_size=5,  # Размер пула соединений
    max_overflow=10,  # Максимум дополнительных соединений
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting async database sessions.
    
    Yields:
        AsyncSession: Database session
        
    Example:
        ```python
        from fastapi import Depends
        from app.db.session import get_db
        
        @app.get("/users")
        async def get_users(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(User))
            return result.scalars().all()
        ```
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()  # Автокоммит при успехе
        except Exception:
            await session.rollback()  # Откат при ошибке
            raise
        finally:
            await session.close()
