"""
Database layer for companies (clientes) module:
  - companies + brand_kits + competitors
  - posts (approval workflow)
  - research_reports (trends, profile, brand)
  - company_assets (logos, mood board references)

Shares the same SQLite database as db.py (runs.db) via get_conn().
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .db import get_conn, _sqlite_retry


# ─────────────────────────────────────────────────────────────────────────────
# Schema init
# ─────────────────────────────────────────────────────────────────────────────

@_sqlite_retry
def init_companies_db() -> None:
    """Create all company tables if they don't exist (idempotent)."""
    with get_conn() as conn:
        def _ensure_column(table: str, column: str, ddl: str) -> None:
            cols = {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if column not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

        # ── Companies ──────────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                slug        TEXT NOT NULL UNIQUE,
                segment     TEXT,
                city        TEXT,
                state       TEXT,
                website     TEXT,
                phone       TEXT,
                email       TEXT,
                socials     TEXT NOT NULL DEFAULT '{}',
                notes       TEXT,
                active      INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_companies_active ON companies(active)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_companies_slug ON companies(slug)")

        # ── Brand kits ─────────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS brand_kits (
                id                  TEXT PRIMARY KEY,
                company_id          TEXT NOT NULL UNIQUE,
                logo_url            TEXT,
                colors              TEXT NOT NULL DEFAULT '{}',
                voice               TEXT,
                persona             TEXT,
                visual_prompt_base  TEXT,
                extras              TEXT NOT NULL DEFAULT '{}',
                source              TEXT NOT NULL DEFAULT 'MANUAL',
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            )
        """)

        # ── Competitors ────────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS competitors (
                id                TEXT PRIMARY KEY,
                company_id        TEXT NOT NULL,
                name              TEXT NOT NULL,
                handles           TEXT NOT NULL DEFAULT '{}',
                metrics           TEXT NOT NULL DEFAULT '{}',
                dossier           TEXT,
                last_analyzed_at  TEXT,
                created_at        TEXT NOT NULL,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_competitors_company ON competitors(company_id)")

        # ── Posts (approval workflow) ───────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id            TEXT PRIMARY KEY,
                company_id    TEXT NOT NULL,
                status        TEXT NOT NULL DEFAULT 'DRAFT',
                title         TEXT,
                copy          TEXT,
                hashtags      TEXT NOT NULL DEFAULT '',
                networks      TEXT NOT NULL DEFAULT '[]',
                scheduled_at  TEXT,
                published_at  TEXT,
                postiz_id     TEXT,
                error         TEXT,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_company ON posts(company_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_scheduled ON posts(scheduled_at)")

        # ── Research reports ───────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS research_reports (
                id          TEXT PRIMARY KEY,
                company_id  TEXT NOT NULL,
                type        TEXT NOT NULL DEFAULT 'TRENDS',
                status      TEXT NOT NULL DEFAULT 'PENDING',
                payload     TEXT NOT NULL DEFAULT '{}',
                error       TEXT,
                version     INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT NOT NULL,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_company_type ON research_reports(company_id, type)")

        # ── Company assets (logos, references) ─────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS company_assets (
                id          TEXT PRIMARY KEY,
                company_id  TEXT NOT NULL,
                post_id     TEXT,
                kind        TEXT NOT NULL DEFAULT 'IMAGE',
                source      TEXT NOT NULL DEFAULT 'UPLOADED',
                url         TEXT NOT NULL,
                meta        TEXT NOT NULL DEFAULT '{}',
                created_at  TEXT NOT NULL,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_company ON company_assets(company_id)")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def _slugify(name: str) -> str:
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    slug = "".join(c if c.isalnum() or c == "-" else "-" for c in ascii_str.lower()).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "empresa"


# ─────────────────────────────────────────────────────────────────────────────
# Companies CRUD
# ─────────────────────────────────────────────────────────────────────────────

@_sqlite_retry
def company_list(active_only: bool = False, limit: int = 200) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        q = "SELECT * FROM companies"
        if active_only:
            q += " WHERE active = 1"
        q += " ORDER BY created_at DESC LIMIT ?"
        rows = conn.execute(q, (limit,)).fetchall()
        results = []
        for r in rows:
            row = dict(r)
            row["socials"] = json.loads(row.get("socials") or "{}")
            row["active"] = bool(row.get("active", 1))
            # count posts
            pc = conn.execute("SELECT COUNT(*) as c FROM posts WHERE company_id = ?", (row["id"],)).fetchone()
            row["post_count"] = pc["c"] if pc else 0
            results.append(row)
        return results


@_sqlite_retry
def company_get(company_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
        if not row:
            return None
        row = dict(row)
        row["socials"] = json.loads(row.get("socials") or "{}")
        row["active"] = bool(row.get("active", 1))
        # brand kit
        bk = conn.execute("SELECT * FROM brand_kits WHERE company_id = ?", (company_id,)).fetchone()
        if bk:
            row["brand_kit"] = dict(bk)
            row["brand_kit"]["colors"] = json.loads(row["brand_kit"].get("colors") or "{}")
            row["brand_kit"]["extras"] = json.loads(row["brand_kit"].get("extras") or "{}")
        else:
            row["brand_kit"] = None
        return row


@_sqlite_retry
def company_create(data: Dict[str, Any]) -> Dict[str, Any]:
    cid = _uuid()
    now = _now()
    slug = _slugify(data.get("name", "empresa"))
    # ensure unique slug
    with get_conn() as conn:
        base = slug
        n = 1
        while conn.execute("SELECT 1 FROM companies WHERE slug = ?", (slug,)).fetchone():
            slug = f"{base}-{n}"
            n += 1
    socials = json.dumps(data.get("socials") or {})
    conn_data = {
        "id": cid,
        "name": data.get("name", ""),
        "slug": slug,
        "segment": data.get("segment"),
        "city": data.get("city"),
        "state": data.get("state"),
        "website": data.get("website"),
        "phone": data.get("phone"),
        "email": data.get("email"),
        "socials": socials,
        "notes": data.get("notes"),
        "active": 1,
        "created_at": now,
        "updated_at": now,
    }
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO companies (id, name, slug, segment, city, state, website, phone, email, socials, notes, active, created_at, updated_at)
            VALUES (:id, :name, :slug, :segment, :city, :state, :website, :phone, :email, :socials, :notes, :active, :created_at, :updated_at)
        """, conn_data)
    # create inline competitors
    for comp in data.get("competitors") or []:
        if comp.get("name"):
            competitor_create(cid, comp)
    return company_get(cid)


@_sqlite_retry
def company_update(company_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    now = _now()
    fields = []
    values: List[Any] = []
    for key in ("name", "segment", "city", "state", "website", "phone", "email", "notes"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if "socials" in data:
        fields.append("socials = ?")
        values.append(json.dumps(data["socials"] or {}))
    if "active" in data:
        fields.append("active = ?")
        values.append(1 if data["active"] else 0)
    if not fields:
        return company_get(company_id)
    fields.append("updated_at = ?")
    values.append(now)
    values.append(company_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE companies SET {', '.join(fields)} WHERE id = ?", values)
    return company_get(company_id)


@_sqlite_retry
def company_delete(company_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        return cur.rowcount > 0


@_sqlite_retry
def company_resolve_slug(name: str) -> str:
    slug = _slugify(name)
    with get_conn() as conn:
        base = slug
        n = 1
        while conn.execute("SELECT 1 FROM companies WHERE slug = ?", (slug,)).fetchone():
            slug = f"{base}-{n}"
            n += 1
    return slug


# ─────────────────────────────────────────────────────────────────────────────
# Brand kits
# ─────────────────────────────────────────────────────────────────────────────

@_sqlite_retry
def brand_kit_get(company_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM brand_kits WHERE company_id = ?", (company_id,)).fetchone()
        if not row:
            return None
        row = dict(row)
        row["colors"] = json.loads(row.get("colors") or "{}")
        row["extras"] = json.loads(row.get("extras") or "{}")
        return row


@_sqlite_retry
def brand_kit_upsert(company_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    now = _now()
    existing = brand_kit_get(company_id)
    colors = json.dumps(data.get("colors") or (existing.get("colors") if existing else {}))
    extras = json.dumps(data.get("extras") or (existing.get("extras") if existing else {}))
    if existing:
        fields = []
        values: List[Any] = []
        for key in ("logo_url", "voice", "persona", "visual_prompt_base"):
            if key in data:
                fields.append(f"{key} = ?")
                values.append(data[key])
        if "colors" in data:
            fields.append("colors = ?")
            values.append(colors)
        if "extras" in data:
            fields.append("extras = ?")
            values.append(extras)
        if not fields:
            return existing
        fields.append("updated_at = ?")
        values.append(now)
        values.append(existing["id"])
        with get_conn() as conn:
            conn.execute(f"UPDATE brand_kits SET {', '.join(fields)} WHERE id = ?", values)
    else:
        bk_id = _uuid()
        with get_conn() as conn:
            conn.execute("""
                INSERT INTO brand_kits (id, company_id, logo_url, colors, voice, persona, visual_prompt_base, extras, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'MANUAL', ?, ?)
            """, (bk_id, company_id, data.get("logo_url"), colors, data.get("voice"), data.get("persona"), data.get("visual_prompt_base"), extras, now, now))
    return brand_kit_get(company_id)


# ─────────────────────────────────────────────────────────────────────────────
# Competitors
# ─────────────────────────────────────────────────────────────────────────────

@_sqlite_retry
def competitor_list(company_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        if company_id:
            rows = conn.execute("SELECT * FROM competitors WHERE company_id = ? ORDER BY name ASC", (company_id,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT c.*, co.name as company_name FROM competitors c
                JOIN companies co ON c.company_id = co.id
                ORDER BY c.created_at DESC
            """).fetchall()
        results = []
        for r in rows:
            row = dict(r)
            row["handles"] = json.loads(row.get("handles") or "{}")
            row["metrics"] = json.loads(row.get("metrics") or "{}")
            results.append(row)
        return results


@_sqlite_retry
def competitor_create(company_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    cid = _uuid()
    now = _now()
    handles = json.dumps(data.get("handles") or {})
    metrics = json.dumps(data.get("metrics") or {})
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO competitors (id, company_id, name, handles, metrics, dossier, last_analyzed_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (cid, company_id, data.get("name", ""), handles, metrics, data.get("dossier"), data.get("last_analyzed_at"), now))
    return {"id": cid, "company_id": company_id, "name": data.get("name", ""), "handles": data.get("handles") or {}, "metrics": data.get("metrics") or {}}


@_sqlite_retry
def competitor_delete(competitor_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM competitors WHERE id = ?", (competitor_id,))
        return cur.rowcount > 0


# ─────────────────────────────────────────────────────────────────────────────
# Posts (approval workflow)
# ─────────────────────────────────────────────────────────────────────────────

POST_STATUSES = ["DRAFT", "REVIEW", "APPROVED", "SCHEDULED", "PUBLISHED", "FAILED"]

POST_TRANSITIONS = {
    "DRAFT": ["REVIEW"],
    "REVIEW": ["APPROVED", "DRAFT"],
    "APPROVED": ["SCHEDULED", "REVIEW"],
    "SCHEDULED": ["APPROVED"],
}

POST_LABELS = {
    "DRAFT": "Rascunho",
    "REVIEW": "Em revisão",
    "APPROVED": "Aprovado",
    "SCHEDULED": "Agendado",
    "PUBLISHED": "Publicado",
    "FAILED": "Falhou",
}


@_sqlite_retry
def post_list(statuses: Optional[List[str]] = None, company_id: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        q = """
            SELECT p.*, c.name as company_name FROM posts p
            JOIN companies c ON p.company_id = c.id
            WHERE 1=1
        """
        params: List[Any] = []
        if statuses:
            placeholders = ",".join("?" * len(statuses))
            q += f" AND p.status IN ({placeholders})"
            params.extend(statuses)
        if company_id:
            q += " AND p.company_id = ?"
            params.append(company_id)
        q += " ORDER BY p.updated_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(q, params).fetchall()
        results = []
        for r in rows:
            row = dict(r)
            row["networks"] = json.loads(row.get("networks") or "[]")
            row["hashtags"] = [t for t in (row.get("hashtags") or "").split(" ") if t]
            results.append(row)
        return results


@_sqlite_retry
def post_get(post_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("""
            SELECT p.*, c.name as company_name FROM posts p
            JOIN companies c ON p.company_id = c.id
            WHERE p.id = ?
        """, (post_id,)).fetchone()
        if not row:
            return None
        row = dict(row)
        row["networks"] = json.loads(row.get("networks") or "[]")
        row["hashtags"] = [t for t in (row.get("hashtags") or "").split(" ") if t]
        return row


@_sqlite_retry
def post_create(data: Dict[str, Any]) -> Dict[str, Any]:
    pid = _uuid()
    now = _now()
    hashtags = data.get("hashtags") or ""
    if isinstance(hashtags, list):
        hashtags = " ".join(hashtags)
    networks = json.dumps(data.get("networks") or [])
    status = data.get("status", "DRAFT")
    if status not in POST_STATUSES:
        status = "DRAFT"
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO posts (id, company_id, status, title, copy, hashtags, networks, scheduled_at, published_at, postiz_id, error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (pid, data.get("company_id"), status, data.get("title"), data.get("copy"), hashtags, networks, data.get("scheduled_at"), data.get("published_at"), data.get("postiz_id"), data.get("error"), now, now))
    return post_get(pid)


@_sqlite_retry
def post_transition(post_id: str, to_status: str) -> Optional[Dict[str, Any]]:
    post = post_get(post_id)
    if not post:
        return None
    current = post.get("status", "DRAFT")
    allowed = POST_TRANSITIONS.get(current, [])
    if to_status not in allowed:
        return None
    if to_status == "SCHEDULED" and not post.get("scheduled_at"):
        return None
    now = _now()
    with get_conn() as conn:
        conn.execute("UPDATE posts SET status = ?, updated_at = ? WHERE id = ?", (to_status, now, post_id))
    return post_get(post_id)


@_sqlite_retry
def post_update(post_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    now = _now()
    fields = []
    values: List[Any] = []
    for key in ("title", "copy", "scheduled_at", "published_at", "postiz_id", "error"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if "hashtags" in data:
        ht = data["hashtags"]
        if isinstance(ht, list):
            ht = " ".join(ht)
        fields.append("hashtags = ?")
        values.append(ht)
    if "networks" in data:
        fields.append("networks = ?")
        values.append(json.dumps(data["networks"] or []))
    if not fields:
        return post_get(post_id)
    fields.append("updated_at = ?")
    values.append(now)
    values.append(post_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE posts SET {', '.join(fields)} WHERE id = ?", values)
    return post_get(post_id)


@_sqlite_retry
def post_delete(post_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        return cur.rowcount > 0


@_sqlite_retry
def post_stats() -> Dict[str, Any]:
    with get_conn() as conn:
        total_companies = conn.execute("SELECT COUNT(*) as c FROM companies WHERE active = 1").fetchone()
        stats = {"companies": total_companies["c"] if total_companies else 0}
        for status in POST_STATUSES:
            r = conn.execute("SELECT COUNT(*) as c FROM posts WHERE status = ?", (status,)).fetchone()
            stats[status.lower()] = r["c"] if r else 0
        # next scheduled
        sched = conn.execute("""
            SELECT p.*, c.name as company_name FROM posts p
            JOIN companies c ON p.company_id = c.id
            WHERE p.status = 'SCHEDULED' AND p.scheduled_at IS NOT NULL
            ORDER BY p.scheduled_at ASC LIMIT 5
        """).fetchall()
        stats["next_scheduled"] = [dict(r) for r in sched]
        # recent
        recent = conn.execute("""
            SELECT p.*, c.name as company_name FROM posts p
            JOIN companies c ON p.company_id = c.id
            ORDER BY p.updated_at DESC LIMIT 6
        """).fetchall()
        stats["recent"] = [dict(r) for r in recent]
        return stats


# ─────────────────────────────────────────────────────────────────────────────
# Research reports
# ─────────────────────────────────────────────────────────────────────────────

@_sqlite_retry
def report_get_latest(company_id: str, report_type: str = "TRENDS") -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("""
            SELECT * FROM research_reports
            WHERE company_id = ? AND type = ? AND status = 'DONE'
            ORDER BY created_at DESC LIMIT 1
        """, (company_id, report_type)).fetchone()
        if not row:
            return None
        row = dict(row)
        row["payload"] = json.loads(row.get("payload") or "{}")
        return row


@_sqlite_retry
def report_create(company_id: str, report_type: str, payload: Dict[str, Any], status: str = "DONE") -> Dict[str, Any]:
    rid = _uuid()
    now = _now()
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO research_reports (id, company_id, type, status, payload, error, version, created_at)
            VALUES (?, ?, ?, ?, ?, NULL, 1, ?)
        """, (rid, company_id, report_type, status, json.dumps(payload), now))
    return {"id": rid, "company_id": company_id, "type": report_type, "status": status, "payload": payload}


# ─────────────────────────────────────────────────────────────────────────────
# Company assets
# ─────────────────────────────────────────────────────────────────────────────

@_sqlite_retry
def asset_list(company_id: str, role: Optional[str] = None) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        if role:
            rows = conn.execute("""
                SELECT * FROM company_assets WHERE company_id = ? AND post_id IS NULL
                AND json_extract(meta, '$.role') = ?
                ORDER BY created_at DESC
            """, (company_id, role)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM company_assets WHERE company_id = ? ORDER BY created_at DESC", (company_id,)).fetchall()
        results = []
        for r in rows:
            row = dict(r)
            row["meta"] = json.loads(row.get("meta") or "{}")
            results.append(row)
        return results


@_sqlite_retry
def asset_create(company_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    aid = _uuid()
    now = _now()
    meta = json.dumps(data.get("meta") or {})
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO company_assets (id, company_id, post_id, kind, source, url, meta, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (aid, company_id, data.get("post_id"), data.get("kind", "IMAGE"), data.get("source", "UPLOADED"), data.get("url", ""), meta, now))
    return {"id": aid, "company_id": company_id, "kind": data.get("kind", "IMAGE"), "source": data.get("source", "UPLOADED"), "url": data.get("url", ""), "meta": data.get("meta") or {}}


@_sqlite_retry
def asset_delete(asset_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM company_assets WHERE id = ?", (asset_id,))
        return cur.rowcount > 0
