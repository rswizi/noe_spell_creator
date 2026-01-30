import os
import uuid
from datetime import datetime
from typing import AsyncGenerator

from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

_raw_url = os.environ.get("DATABASE_URL") or "sqlite+aiosqlite:///./wiki.db"
if _raw_url.startswith("postgresql://") and "+asyncpg" not in _raw_url:
    DATABASE_URL = _raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    DATABASE_URL = _raw_url

engine = create_async_engine(DATABASE_URL, future=True, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
DOC_JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")
IS_POSTGRES = DATABASE_URL.startswith("postgresql")
ID_COLUMN_TYPE = PG_UUID(as_uuid=True) if IS_POSTGRES else String(36)


def _new_id():
    val = uuid.uuid4()
    return val if IS_POSTGRES else str(val)


class Base(DeclarativeBase):
    pass


class WikiPage(Base):
    __tablename__ = "wiki_pages"

    id: Mapped[str | uuid.UUID] = mapped_column(
        ID_COLUMN_TYPE,
        primary_key=True,
        default=_new_id,
    )
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    doc_json: Mapped[dict] = mapped_column(DOC_JSON_TYPE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    revisions: Mapped[list["WikiRevision"]] = relationship(
        "WikiRevision", back_populates="page", cascade="all, delete-orphan"
    )


class WikiRevision(Base):
    __tablename__ = "wiki_revisions"

    id: Mapped[str | uuid.UUID] = mapped_column(
        ID_COLUMN_TYPE,
        primary_key=True,
        default=_new_id,
    )
    page_id: Mapped[str | uuid.UUID] = mapped_column(
        ID_COLUMN_TYPE,
        ForeignKey("wiki_pages.id", ondelete="CASCADE"),
        nullable=False,
    )
    doc_json: Mapped[dict] = mapped_column(DOC_JSON_TYPE, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    page: Mapped[WikiPage] = relationship("WikiPage", back_populates="revisions")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
