"""Warehouse connection helper.

Reads WAREHOUSE_URL (the dbt/app connection string) and hands back a psycopg
connection. psycopg wants a plain ``postgresql://`` DSN, so the SQLAlchemy-style
``postgresql+psycopg://`` prefix is normalised away.
"""

from __future__ import annotations

import os

import psycopg

DEFAULT_URL = "postgresql://postgres:postgres@localhost:5432/lakehouse"


def warehouse_dsn(url: str | None = None) -> str:
    """Return a psycopg-compatible DSN from WAREHOUSE_URL (or an explicit url)."""
    raw = url or os.environ.get("WAREHOUSE_URL") or DEFAULT_URL
    return raw.replace("postgresql+psycopg://", "postgresql://", 1)


def connect(url: str | None = None, **kwargs) -> psycopg.Connection:
    """Open a psycopg connection to the warehouse."""
    return psycopg.connect(warehouse_dsn(url), **kwargs)
