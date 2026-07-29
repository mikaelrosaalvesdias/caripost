"""
Versioned, idempotent schema-migration runner — single source of truth for
schema changes across db.py and db_companies.py (avoids two schema patterns).

Design (Marco 0):
  - Cross-process safe: a file lock (fcntl.flock) serializes concurrent swarm
    replicas at startup, so the guarded ALTER TABLE ... ADD COLUMN statements
    in init_db()/init_companies_db() can never race between replicas.
  - Idempotent: every migration is recorded in the `schema_migrations` ledger;
    re-running the runner is a no-op. Wrapped in BEGIN IMMEDIATE as a second
    layer of serialization at the DB level (NOT PRAGMA locking_mode, which only
    isolates within a single connection).
  - Additive only: SQLite has no easy DROP COLUMN, so migrations only ADD.
    Rollback of a bad marco = manual column drop → validate before deploy.

Usage:
  from .migrations import schema_lock, run_migrations, ensure_column
  with schema_lock():
      init_db(); init_agency_db(); init_companies_db()
      run_migrations(_locked=True)
"""
from __future__ import annotations

import fcntl
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, List, Tuple

from .db import DB_PATH, get_conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def schema_lock():
    """Cross-process advisory lock: only one replica mutates schema at a time.

    Do NOT nest a second schema_lock() in the same process — flock on a new fd
    would block on the lock this process already holds (self-deadlock). Pass
    _locked=True to run_migrations() when already inside this context.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_path = DB_PATH.parent / ".schema-migrate.lock"
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return column in {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """Idempotent ADD COLUMN. Tolerates the duplicate-column race defensively.

    `ddl` is the full column spec, e.g. "flow_id TEXT" or "layout_variant TEXT".
    """
    if column_exists(conn, table, column):
        return
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise


def ensure_index(conn: sqlite3.Connection, name: str, table: str, columns: str) -> None:
    """Idempotent CREATE INDEX. `columns` e.g. "flow_id" or "company_id, status"."""
    conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})")


# ── Migration registry ────────────────────────────────────────────────────
# Each entry: (version:int, name:str, fn(conn)->None). fn MUST be idempotent.
# Append-only. Marco 2 will add flow_id/flow_label; Marco 3 layout_variant; etc.

def _m1_baseline(conn: sqlite3.Connection) -> None:
    # Baseline: existing tables are created by init_db()/init_companies_db().
    # This entry only records that the versioned runner is live end-to-end.
    return None


def _m2_billing(conn: sqlite3.Connection) -> None:
    """Marco 4 (venda de acesso): medição de gasto POR EMPRESA + saldo de créditos + feature flags."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS usage_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "company_id TEXT NOT NULL, "
        "kind TEXT NOT NULL, "              # image | video | text | enrich ...
        "provider TEXT, model TEXT, "
        "cost_usd REAL NOT NULL DEFAULT 0, "
        "credits REAL NOT NULL DEFAULT 0, "
        "meta TEXT NOT NULL DEFAULT '{}', "
        "created_at TEXT NOT NULL)"
    )
    ensure_index(conn, "idx_usage_company", "usage_log", "company_id, created_at")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS company_credits ("
        "company_id TEXT PRIMARY KEY, "
        "balance REAL NOT NULL DEFAULT 0, "
        "updated_at TEXT NOT NULL)"
    )
    ensure_column(conn, "companies", "features", "features TEXT NOT NULL DEFAULT '{}'")


def _m3_tenancy(conn: sqlite3.Connection) -> None:
    """Marco A (produto vendável): usuário amarrado à empresa (NULL = super-admin/staff da agência)."""
    ensure_column(conn, "app_users", "company_id", "company_id TEXT")
    ensure_index(conn, "idx_app_users_company", "app_users", "company_id")


def _m4_agency(conn: sqlite3.Connection) -> None:
    """Duas categorias de cliente: CLIENTE FINAL (1 empresa) e AGÊNCIA (dona de VÁRIAS empresas).
    companies.owner_user_id = user (role agency) dono da empresa; NULL = empresa da casa (super-admin)."""
    ensure_column(conn, "companies", "owner_user_id", "owner_user_id TEXT")
    ensure_index(conn, "idx_companies_owner", "companies", "owner_user_id")


MIGRATIONS: List[Tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "baseline", _m1_baseline),
    (2, "billing", _m2_billing),
    (3, "tenancy", _m3_tenancy),
    (4, "agency", _m4_agency),
]


def _ensure_ledger(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY, "
        "name TEXT NOT NULL, "
        "applied_at TEXT NOT NULL)"
    )


def _run_body() -> List[int]:
    applied: List[int] = []
    conn = get_conn()
    conn.isolation_level = None  # manual transaction control for BEGIN IMMEDIATE
    try:
        _ensure_ledger(conn)
        done = {int(r[0]) for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}
        for version, name, fn in sorted(MIGRATIONS, key=lambda m: m[0]):
            if version in done:
                continue
            conn.execute("BEGIN IMMEDIATE")
            try:
                fn(conn)
                conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                    (version, name, _now_iso()),
                )
                conn.execute("COMMIT")
                applied.append(version)
            except Exception:
                conn.execute("ROLLBACK")
                raise
    finally:
        conn.close()
    return applied


def run_migrations(_locked: bool = False) -> List[int]:
    """Apply pending migrations. Returns the list of versions applied this call.

    Pass _locked=True only when already inside a schema_lock() context (e.g.
    startup, right after the init_*_db() calls) to avoid a self-deadlock.
    """
    if _locked:
        applied = _run_body()
    else:
        with schema_lock():
            applied = _run_body()
    if applied:
        print(f"[migrations] applied: {applied}", flush=True)
    return applied
