from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


class Database:
    """Lazy so importing the app never opens a connection; tests call configure()."""

    def __init__(self) -> None:
        self.engine = None
        self._maker: async_sessionmaker[AsyncSession] | None = None

    def configure(self, url: str, **kw) -> None:
        self.engine = create_async_engine(url, **kw)
        self._maker = async_sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> AsyncSession:
        if self._maker is None:
            self.configure(settings.database_url)
        return self._maker()

    async def create_all(self) -> None:
        if self.engine is None:
            self.configure(settings.database_url)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


db = Database()
