"""Async SQLAlchemy engine factory."""

from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import create_async_engine as _create_engine


def create_async_engine(url: str, **kwargs) -> AsyncEngine:
    """Create an async SQLAlchemy engine from a database URL.

    Args:
        url: Database URL (e.g., postgresql+asyncpg://user:pass@host/db)
        **kwargs: Additional engine options (pool_size, echo, etc.)
    """
    defaults = {
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 10,
    }
    defaults.update(kwargs)
    return _create_engine(url, **defaults)
