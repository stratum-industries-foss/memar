"""Async SQLAlchemy database configuration and session management."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from .models_db import Base
import os


MEMAR_DB_PATH = os.getenv("MEMAR_DB_PATH", "./memar.db")
# Create the database's directory on first start (a fresh Docker volume or data
# dir may not have it yet); SQLite creates the file but not missing parents.
if MEMAR_DB_PATH != ":memory:":
    try:
        os.makedirs(os.path.dirname(os.path.abspath(MEMAR_DB_PATH)), exist_ok=True)
    except OSError:
        pass  # startup will report the real error when the DB cannot be opened
DATABASE_URL = f"sqlite+aiosqlite:///{MEMAR_DB_PATH}"

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# Columns ADDED to PRE-EXISTING tables after the initial release. create_all
# only issues CREATE TABLE for missing tables — it never ALTERs an existing one —
# so on an upgraded database these columns must be added explicitly here. New
# tables don't belong in this map (create_all handles them). SQLite ADD COLUMN
# (nullable, no default) is safe and idempotent given the existence check.
_ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "webhooks": [("secret", "VARCHAR(64)")],
    "cnc_metrics_log": [("tool_id", "VARCHAR(50)")],
    "issued_licenses": [("renewal_warning_sent_at", "DATETIME")],
    # Audit hash chain (audit.py): NULL on rows written before the chain existed.
    "audit_log": [("prev_hash", "VARCHAR(64)"), ("row_hash", "VARCHAR(64)")],
    "sso_settings": [
        ("saml_idp_entity_id", "VARCHAR(500)"),
        ("saml_idp_sso_url", "VARCHAR(500)"),
        ("saml_idp_cert_pem", "TEXT"),
        ("saml_sp_entity_id", "VARCHAR(500)"),
    ],
    "users": [
        ("must_change_password", "BOOLEAN NOT NULL DEFAULT 0"),
        ("auth_provider", "VARCHAR(20) NOT NULL DEFAULT 'local'"),
    ],
}


async def _ensure_added_columns(conn) -> None:
    for table, cols in _ADDED_COLUMNS.items():
        try:
            rows = (await conn.exec_driver_sql(f'PRAGMA table_info("{table}")')).fetchall()
        except Exception:
            continue  # table doesn't exist yet on this engine; create_all made it
        existing = {r[1] for r in rows}
        if not existing:
            continue
        for name, ddl in cols:
            if name not in existing:
                await conn.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN {name} {ddl}')


async def init_db() -> None:
    """Create all tables and apply lightweight additive column migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_added_columns(conn)


async def get_db():
    """FastAPI dependency: yields an AsyncSession for route handlers."""
    async with AsyncSessionLocal() as session:
        yield session
