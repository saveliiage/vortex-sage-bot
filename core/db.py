"""DB engine/session helpers for Vortex — SQLAlchemy, engine-agnostic (Postgres prod, SQLite test)."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session


def create_db_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine from a database URL.

    Handles SQLite-specific connect_args (same-thread checkmode).
    """
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(database_url, echo=echo, connect_args=connect_args)


def get_session(engine: Engine) -> Session:
    """Return a new SQLAlchemy ORM Session bound to *engine*."""
    return Session(engine)
