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


def _m5_company_lifecycle(conn: sqlite3.Connection) -> None:
    """Prospecting lifecycle. Pre-existing rows keep managed-client semantics."""
    ensure_column(
        conn, "companies", "lifecycle_stage",
        "lifecycle_stage TEXT NOT NULL DEFAULT 'managed' "
        "CHECK (lifecycle_stage IN ('prospect', 'managed', 'internal', 'lost'))",
    )
    ensure_column(conn, "companies", "converted_at", "converted_at TEXT")
    ensure_index(conn, "idx_companies_lifecycle", "companies", "lifecycle_stage")


def _m6_product_catalog(conn: sqlite3.Connection) -> None:
    """Hierarchical catalog and explicit links from clients to shared offers."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS product_groups ("
        "id TEXT PRIMARY KEY, "
        "company_id TEXT NOT NULL, "
        "name TEXT NOT NULL, "
        "description TEXT, "
        "active INTEGER NOT NULL DEFAULT 1, "
        "created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, "
        "FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE)"
    )
    ensure_index(conn, "idx_product_groups_company", "product_groups", "company_id")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_product_groups_company_name "
        "ON product_groups(company_id, name COLLATE NOCASE)"
    )

    ensure_column(
        conn, "products", "group_id",
        "group_id TEXT REFERENCES product_groups(id) ON DELETE RESTRICT",
    )
    ensure_index(conn, "idx_products_group", "products", "group_id")

    conn.execute(
        "CREATE TABLE IF NOT EXISTS product_plans ("
        "id TEXT PRIMARY KEY, "
        "company_id TEXT NOT NULL, "
        "product_id TEXT NOT NULL, "
        "name TEXT NOT NULL, "
        "description TEXT, "
        "features TEXT NOT NULL DEFAULT '[]', "
        "active INTEGER NOT NULL DEFAULT 1, "
        "sort_order INTEGER NOT NULL DEFAULT 0, "
        "created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, "
        "FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE, "
        "FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE)"
    )
    # Defensive for databases initialized by a short-lived pre-release schema.
    ensure_column(conn, "product_plans", "features", "features TEXT NOT NULL DEFAULT '[]'")
    ensure_column(conn, "product_plans", "sort_order", "sort_order INTEGER NOT NULL DEFAULT 0")
    ensure_index(conn, "idx_product_plans_company", "product_plans", "company_id")
    ensure_index(conn, "idx_product_plans_product", "product_plans", "product_id")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_product_plans_product_name "
        "ON product_plans(product_id, name COLLATE NOCASE)"
    )

    conn.execute(
        "CREATE TABLE IF NOT EXISTS company_catalog_links ("
        "id TEXT PRIMARY KEY, "
        "company_id TEXT NOT NULL, "
        "source_company_id TEXT NOT NULL, "
        "product_id TEXT NOT NULL, "
        "plan_id TEXT, "
        "solution_ids TEXT NOT NULL DEFAULT '[]', "
        "notes TEXT, "
        "active INTEGER NOT NULL DEFAULT 1, "
        "created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, "
        "FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE, "
        "FOREIGN KEY (source_company_id) REFERENCES companies(id) ON DELETE RESTRICT, "
        "FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT, "
        "FOREIGN KEY (plan_id) REFERENCES product_plans(id) ON DELETE RESTRICT)"
    )
    ensure_index(conn, "idx_catalog_links_company", "company_catalog_links", "company_id")
    ensure_index(conn, "idx_catalog_links_source", "company_catalog_links", "source_company_id")
    ensure_index(conn, "idx_catalog_links_product", "company_catalog_links", "product_id")
    ensure_index(conn, "idx_catalog_links_plan", "company_catalog_links", "plan_id")


def _m7_solution_catalog_profile(conn: sqlite3.Connection) -> None:
    """Promote à-la-carte solutions to complete, asset-backed catalog entries."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS solutions ("
        "id TEXT PRIMARY KEY, "
        "company_id TEXT NOT NULL, "
        "product_id TEXT NOT NULL, "
        "name TEXT NOT NULL, "
        "description TEXT, "
        "category TEXT, "
        "website TEXT, "
        "socials TEXT NOT NULL DEFAULT '{}', "
        "colors TEXT NOT NULL DEFAULT '{}', "
        "objective TEXT, "
        "functions TEXT NOT NULL DEFAULT '[]', "
        "knowledge TEXT, "
        "web_brief TEXT, "
        "web_brief_at TEXT, "
        "links TEXT NOT NULL DEFAULT '[]', "
        "active INTEGER NOT NULL DEFAULT 1, "
        "created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, "
        "FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE)"
    )
    for column, ddl in (
        ("category", "category TEXT"),
        ("website", "website TEXT"),
        ("socials", "socials TEXT NOT NULL DEFAULT '{}'"),
        ("colors", "colors TEXT NOT NULL DEFAULT '{}'"),
        ("objective", "objective TEXT"),
        ("functions", "functions TEXT NOT NULL DEFAULT '[]'"),
        ("knowledge", "knowledge TEXT"),
        ("web_brief", "web_brief TEXT"),
        ("web_brief_at", "web_brief_at TEXT"),
    ):
        ensure_column(conn, "solutions", column, ddl)
    ensure_index(conn, "idx_solutions_product", "solutions", "product_id")
    ensure_index(conn, "idx_solutions_company", "solutions", "company_id")

    conn.execute(
        "CREATE TABLE IF NOT EXISTS company_assets ("
        "id TEXT PRIMARY KEY, "
        "company_id TEXT NOT NULL, "
        "product_id TEXT, "
        "solution_id TEXT, "
        "post_id TEXT, "
        "kind TEXT NOT NULL DEFAULT 'IMAGE', "
        "source TEXT NOT NULL DEFAULT 'UPLOADED', "
        "url TEXT NOT NULL, "
        "meta TEXT NOT NULL DEFAULT '{}', "
        "created_at TEXT NOT NULL, "
        "FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE)"
    )
    ensure_column(conn, "company_assets", "solution_id", "solution_id TEXT")
    ensure_index(conn, "idx_assets_solution", "company_assets", "solution_id")


MIGRATIONS: List[Tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "baseline", _m1_baseline),
    (2, "billing", _m2_billing),
    (3, "tenancy", _m3_tenancy),
    (4, "agency", _m4_agency),
    (5, "company_lifecycle", _m5_company_lifecycle),
    (6, "product_catalog", _m6_product_catalog),
    (7, "solution_catalog_profile", _m7_solution_catalog_profile),
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
