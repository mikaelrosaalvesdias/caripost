"""
Database layer for agency modules:
  - creators + platform_accounts
  - publish_jobs + publications
  - trends_raw + trend_briefings
  - dmca_infringements
  - calendar_entries
  - earning_records
  - creator_stats + video_stats

Shares the same SQLite database as db.py (runs.db) via get_conn().
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Dict, List, Optional

from .db import get_conn, _sqlite_retry  # reuse connection + retry decorator


# ─────────────────────────────────────────────────────────────────────────────
# Schema init
# ─────────────────────────────────────────────────────────────────────────────

@_sqlite_retry
def init_agency_db() -> None:
    """Create all agency tables if they don't exist (idempotent)."""
    with get_conn() as conn:
        def _ensure_column(table: str, column: str, ddl: str) -> None:
            cols = {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if column not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

        # ── Creators ─────────────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS creators (
                creator_id      TEXT PRIMARY KEY,
                name            TEXT NOT NULL,
                slug            TEXT,
                real_name       TEXT,
                email           TEXT NOT NULL,
                phone           TEXT,
                whatsapp        TEXT,
                status          TEXT NOT NULL DEFAULT 'trial',
                logo_b64        TEXT,
                logo_position   TEXT NOT NULL DEFAULT 'bottom-right',
                logo_opacity    REAL NOT NULL DEFAULT 0.7,
                commission_model TEXT NOT NULL DEFAULT 'percentage',
                commission_pct  REAL NOT NULL DEFAULT 25.0,
                fixed_monthly   REAL NOT NULL DEFAULT 0.0,
                content_language TEXT NOT NULL DEFAULT 'pt-BR',
                notification_email    INTEGER NOT NULL DEFAULT 1,
                notification_whatsapp INTEGER NOT NULL DEFAULT 0,
                trend_report_frequency TEXT NOT NULL DEFAULT 'weekly',
                drive_folder_id TEXT,
                drive_service_account TEXT,
                portal_branding TEXT NOT NULL DEFAULT '{}',
                default_edit_config TEXT NOT NULL DEFAULT '{}',
                reference_channels  TEXT NOT NULL DEFAULT '[]',
                preferred_categories TEXT NOT NULL DEFAULT '[]',
                preferred_tags      TEXT NOT NULL DEFAULT '[]',
                notes           TEXT,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
        """)
        _ensure_column("creators", "slug", "slug TEXT")
        _ensure_column("creators", "portal_branding", "portal_branding TEXT NOT NULL DEFAULT '{}'")
        # Production profile columns (added 2026-04)
        _ensure_column("creators", "own_channel_urls", "own_channel_urls TEXT NOT NULL DEFAULT '[]'")
        _ensure_column("creators", "filming_setups", "filming_setups TEXT NOT NULL DEFAULT '[]'")
        _ensure_column("creators", "location_types", "location_types TEXT NOT NULL DEFAULT '[]'")
        _ensure_column("creators", "production_level", "production_level TEXT NOT NULL DEFAULT 'amateur'")
        _ensure_column("creators", "performer_description", "performer_description TEXT")
        _ensure_column("creators", "production_constraints", "production_constraints TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_creators_status ON creators(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_creators_email ON creators(email)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_creators_slug ON creators(slug)")
        _backfill_creator_slugs(conn)

        # ── Platform accounts ─────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS platform_accounts (
                id                TEXT PRIMARY KEY,
                creator_id        TEXT NOT NULL,
                platform          TEXT NOT NULL,
                username          TEXT NOT NULL,
                profile_url       TEXT,
                cookies_json      TEXT,
                is_verified       INTEGER NOT NULL DEFAULT 0,
                partner_program   INTEGER NOT NULL DEFAULT 0,
                last_login_check  TEXT,
                status            TEXT NOT NULL DEFAULT 'active',
                FOREIGN KEY (creator_id) REFERENCES creators(creator_id)
            )
        """)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_pa_creator_platform ON platform_accounts(creator_id, platform)")

        # ── Publish jobs ──────────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS publish_jobs (
                job_id              TEXT PRIMARY KEY,
                creator_id          TEXT NOT NULL,
                video_object_key    TEXT NOT NULL,
                thumbnail_object_key TEXT,
                platforms           TEXT NOT NULL DEFAULT '[]',
                metadata_json       TEXT NOT NULL DEFAULT '{}',
                schedule_at         TEXT,
                status              TEXT NOT NULL DEFAULT 'pending',
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_publish_jobs_creator ON publish_jobs(creator_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_publish_jobs_status ON publish_jobs(status, schedule_at)")
        _ensure_column("publish_jobs", "progress_pct", "progress_pct INTEGER NOT NULL DEFAULT 0")
        _ensure_column("publish_jobs", "detail", "detail TEXT NOT NULL DEFAULT ''")

        # ── Publication results (one row per platform per job) ────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS publications (
                pub_id              TEXT PRIMARY KEY,
                job_id              TEXT NOT NULL,
                creator_id          TEXT NOT NULL,
                platform            TEXT NOT NULL,
                status              TEXT NOT NULL DEFAULT 'queued',
                video_url           TEXT,
                video_id_platform   TEXT,
                error_msg           TEXT,
                screenshot_path     TEXT,
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES publish_jobs(job_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_publications_job ON publications(job_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_publications_creator ON publications(creator_id)")

        # ── Social Integration Layer ────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS social_connections (
                id                     TEXT PRIMARY KEY,
                user_id                TEXT NOT NULL DEFAULT 'api',
                brand_id               TEXT NOT NULL,
                provider               TEXT NOT NULL DEFAULT 'composio',
                platform               TEXT NOT NULL,
                external_account_id    TEXT,
                external_account_name  TEXT,
                composio_entity_id     TEXT,
                composio_connection_id TEXT,
                status                 TEXT NOT NULL DEFAULT 'connected',
                scopes                 TEXT NOT NULL DEFAULT '[]',
                metadata_json          TEXT NOT NULL DEFAULT '{}',
                created_at             TEXT NOT NULL,
                updated_at             TEXT NOT NULL,
                last_sync_at           TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_social_connections_brand ON social_connections(brand_id, platform, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_social_connections_composio ON social_connections(composio_connection_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS social_posts (
                id            TEXT PRIMARY KEY,
                user_id       TEXT NOT NULL DEFAULT 'api',
                brand_id      TEXT NOT NULL,
                source_post_id TEXT,
                title         TEXT,
                caption       TEXT NOT NULL DEFAULT '',
                content_type  TEXT NOT NULL DEFAULT 'text',
                status        TEXT NOT NULL DEFAULT 'draft',
                scheduled_at  TEXT,
                published_at  TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_social_posts_brand ON social_posts(brand_id, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_social_posts_due ON social_posts(status, scheduled_at)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS social_post_channels (
                id                   TEXT PRIMARY KEY,
                post_id              TEXT NOT NULL,
                social_connection_id TEXT NOT NULL,
                platform             TEXT NOT NULL,
                status               TEXT NOT NULL DEFAULT 'pending',
                external_post_id     TEXT,
                external_post_url    TEXT,
                error_message        TEXT,
                retry_count          INTEGER NOT NULL DEFAULT 0,
                metadata_json        TEXT NOT NULL DEFAULT '{}',
                created_at           TEXT NOT NULL,
                updated_at           TEXT NOT NULL,
                FOREIGN KEY (post_id) REFERENCES social_posts(id),
                FOREIGN KEY (social_connection_id) REFERENCES social_connections(id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_social_channels_post ON social_post_channels(post_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_social_channels_status ON social_post_channels(status, platform)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS social_post_assets (
                id               TEXT PRIMARY KEY,
                post_id          TEXT NOT NULL,
                asset_type       TEXT NOT NULL DEFAULT 'image',
                asset_url        TEXT NOT NULL,
                storage_provider TEXT,
                mime_type        TEXT,
                size_bytes       INTEGER,
                width            INTEGER,
                height           INTEGER,
                duration_seconds REAL,
                created_at       TEXT NOT NULL,
                FOREIGN KEY (post_id) REFERENCES social_posts(id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_social_assets_post ON social_post_assets(post_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS social_post_logs (
                id                     TEXT PRIMARY KEY,
                post_id                TEXT NOT NULL,
                social_post_channel_id TEXT,
                level                  TEXT NOT NULL DEFAULT 'info',
                message                TEXT NOT NULL,
                payload_json           TEXT NOT NULL DEFAULT '{}',
                created_at             TEXT NOT NULL,
                FOREIGN KEY (post_id) REFERENCES social_posts(id),
                FOREIGN KEY (social_post_channel_id) REFERENCES social_post_channels(id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_social_logs_post ON social_post_logs(post_id, created_at)")

        # ── Selector maps (stored per-platform, editable via API) ─────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS selector_maps (
                platform  TEXT PRIMARY KEY,
                version   TEXT NOT NULL DEFAULT '2026-01',
                data_json TEXT NOT NULL DEFAULT '{}'
            )
        """)

        # ── Trends raw data ───────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trends_raw (
                id           TEXT PRIMARY KEY,
                platform     TEXT NOT NULL,
                collected_at TEXT NOT NULL,
                data_type    TEXT NOT NULL,
                data_json    TEXT NOT NULL DEFAULT '{}'
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trends_raw_type ON trends_raw(platform, data_type, collected_at)")

        # ── Trend briefings ───────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trend_briefings (
                briefing_id     TEXT PRIMARY KEY,
                creator_id      TEXT NOT NULL,
                content_json    TEXT NOT NULL DEFAULT '{}',
                generated_at    TEXT NOT NULL,
                sent_email      INTEGER NOT NULL DEFAULT 0,
                sent_whatsapp   INTEGER NOT NULL DEFAULT 0,
                email_sent_at   TEXT,
                whatsapp_sent_at TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_briefings_creator ON trend_briefings(creator_id)")

        # ── DMCA infringements ────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dmca_infringements (
                infringement_id  TEXT PRIMARY KEY,
                creator_id       TEXT NOT NULL,
                original_video_id TEXT,
                original_url     TEXT NOT NULL,
                infringing_url   TEXT NOT NULL,
                infringing_site  TEXT NOT NULL,
                detection_method TEXT NOT NULL,
                confidence       REAL NOT NULL DEFAULT 0.0,
                status           TEXT NOT NULL DEFAULT 'detected',
                takedown_sent_at TEXT,
                removed_at       TEXT,
                notes            TEXT NOT NULL DEFAULT '',
                detected_at      TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dmca_creator ON dmca_infringements(creator_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dmca_status ON dmca_infringements(status)")

        # ── Calendar entries ──────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS calendar_entries (
                entry_id             TEXT PRIMARY KEY,
                creator_id           TEXT NOT NULL,
                video_object_key     TEXT NOT NULL,
                run_id               TEXT,
                publish_platforms    TEXT NOT NULL DEFAULT '[]',
                publish_at           TEXT NOT NULL,
                published            INTEGER NOT NULL DEFAULT 0,
                publish_results      TEXT NOT NULL DEFAULT '{}',
                cross_promote        INTEGER NOT NULL DEFAULT 1,
                cross_channels       TEXT NOT NULL DEFAULT '[]',
                cross_promote_at     TEXT,
                cross_results        TEXT NOT NULL DEFAULT '{}',
                title                TEXT NOT NULL DEFAULT '',
                description          TEXT NOT NULL DEFAULT '',
                tags                 TEXT NOT NULL DEFAULT '[]',
                category             TEXT NOT NULL DEFAULT 'Amateur',
                status               TEXT NOT NULL DEFAULT 'scheduled',
                created_at           TEXT NOT NULL,
                updated_at           TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calendar_creator ON calendar_entries(creator_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calendar_publish_at ON calendar_entries(publish_at, status)")

        # ── Earning records ───────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS earning_records (
                record_id         TEXT PRIMARY KEY,
                creator_id        TEXT NOT NULL,
                platform          TEXT NOT NULL,
                period            TEXT NOT NULL,
                video_id          TEXT,
                gross_revenue     REAL NOT NULL DEFAULT 0.0,
                platform_fee      REAL NOT NULL DEFAULT 0.0,
                net_revenue       REAL NOT NULL DEFAULT 0.0,
                agency_commission REAL NOT NULL DEFAULT 0.0,
                creator_payout    REAL NOT NULL DEFAULT 0.0,
                views_in_period   INTEGER NOT NULL DEFAULT 0,
                source            TEXT NOT NULL DEFAULT 'scraped',
                scraped_at        TEXT,
                created_at        TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_earnings_creator_period ON earning_records(creator_id, period)")

        # ── Creator stats (channel-level, scraped periodically) ───────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS creator_stats (
                stat_id      TEXT PRIMARY KEY,
                creator_id   TEXT NOT NULL,
                platform     TEXT NOT NULL,
                scraped_at   TEXT NOT NULL,
                total_views  INTEGER NOT NULL DEFAULT 0,
                subscribers  INTEGER NOT NULL DEFAULT 0,
                total_videos INTEGER NOT NULL DEFAULT 0,
                earnings     REAL NOT NULL DEFAULT 0.0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_creator_stats ON creator_stats(creator_id, platform, scraped_at)")

        # ── Video stats (per video, per platform) ─────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS video_stats (
                stat_id    TEXT PRIMARY KEY,
                creator_id TEXT NOT NULL,
                platform   TEXT NOT NULL,
                video_id   TEXT NOT NULL,
                scraped_at TEXT NOT NULL,
                views      INTEGER NOT NULL DEFAULT 0,
                likes      INTEGER NOT NULL DEFAULT 0,
                dislikes   INTEGER NOT NULL DEFAULT 0,
                comments   INTEGER NOT NULL DEFAULT 0,
                rating     REAL NOT NULL DEFAULT 0.0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_video_stats ON video_stats(creator_id, platform, video_id)")

        # ── User activity log ────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_activity_log (
                log_id     TEXT PRIMARY KEY,
                user_id    TEXT NOT NULL,
                username   TEXT NOT NULL,
                action     TEXT NOT NULL,
                target     TEXT,
                details    TEXT,
                ip         TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ual_user ON user_activity_log(user_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ual_created ON user_activity_log(created_at)")

        # ── App users (login system) ──────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_users (
                user_id       TEXT PRIMARY KEY,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role          TEXT NOT NULL DEFAULT 'viewer',
                permissions   TEXT NOT NULL DEFAULT '[]',
                active        INTEGER NOT NULL DEFAULT 1,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            )
        """)


# ─────────────────────────────────────────────────────────────────────────────
# App Users CRUD
# ─────────────────────────────────────────────────────────────────────────────

@_sqlite_retry
def appuser_create(data: Dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO app_users (user_id, username, password_hash, role, permissions, active, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (data["user_id"], data["username"], data["password_hash"],
             data.get("role", "viewer"),
             json.dumps(data.get("permissions", []), ensure_ascii=False),
             1 if data.get("active", True) else 0,
             data["created_at"], data["updated_at"]),
        )


@_sqlite_retry
def appuser_list() -> List[Dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM app_users ORDER BY username").fetchall()
        return [_appuser_row(r) for r in rows]


@_sqlite_retry
def appuser_get(user_id: str) -> Optional[Dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM app_users WHERE user_id=?", (user_id,)).fetchone()
        return _appuser_row(row) if row else None


@_sqlite_retry
def appuser_get_by_username(username: str) -> Optional[Dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM app_users WHERE username=?", (username,)).fetchone()
        return _appuser_row(row) if row else None


@_sqlite_retry
def appuser_update(user_id: str, data: Dict[str, Any]) -> None:
    fields, vals = [], []
    for key in ("username", "password_hash", "role", "active", "updated_at"):
        if key in data:
            fields.append(f"{key}=?")
            vals.append(data[key])
    if "permissions" in data:
        fields.append("permissions=?")
        vals.append(json.dumps(data["permissions"], ensure_ascii=False))
    if not fields:
        return
    vals.append(user_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE app_users SET {', '.join(fields)} WHERE user_id=?", vals)


@_sqlite_retry
def appuser_delete(user_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM app_users WHERE user_id=?", (user_id,))


@_sqlite_retry
def appuser_count() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM app_users").fetchone()[0]


def _appuser_row(row) -> Dict:
    d = dict(row)
    try:
        d["permissions"] = json.loads(d.get("permissions") or "[]")
    except Exception:
        d["permissions"] = []
    d["active"] = bool(d.get("active", 1))
    d.pop("password_hash", None)
    return d


# ─────────────────────────────────────────────────────────────────────────────
# Activity Log
# ─────────────────────────────────────────────────────────────────────────────

@_sqlite_retry
def activity_log_insert(user_id: str, username: str, action: str,
                        target: Optional[str] = None, details: Optional[str] = None,
                        ip: Optional[str] = None) -> None:
    import uuid as _uuid
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO user_activity_log (log_id, user_id, username, action, target, details, ip, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (str(_uuid.uuid4()), user_id, username, action, target, details, ip, now),
        )


@_sqlite_retry
def activity_log_list(user_id: Optional[str] = None, limit: int = 100) -> List[Dict]:
    with get_conn() as conn:
        if user_id:
            rows = conn.execute(
                "SELECT * FROM user_activity_log WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM user_activity_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Creators CRUD
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_creator_slug(value: str, fallback: str = "criador") -> str:
    raw = unicodedata.normalize("NFKD", str(value or ""))
    raw = raw.encode("ascii", "ignore").decode("ascii")
    raw = re.sub(r"[^a-z0-9]+", "-", raw.strip().lower()).strip("-")
    if raw:
        return raw[:80].strip("-") or fallback
    seed = unicodedata.normalize("NFKD", str(fallback or "criador"))
    seed = seed.encode("ascii", "ignore").decode("ascii")
    seed = re.sub(r"[^a-z0-9]+", "-", seed.strip().lower()).strip("-")
    return (seed or "criador")[:80].strip("-") or "criador"


def _creator_slug_exists(conn, slug: str, exclude_creator_id: Optional[str] = None) -> bool:
    if exclude_creator_id:
        row = conn.execute(
            "SELECT creator_id FROM creators WHERE slug=? AND creator_id<>? LIMIT 1",
            (slug, exclude_creator_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT creator_id FROM creators WHERE slug=? LIMIT 1",
            (slug,),
        ).fetchone()
    return bool(row)


def _ensure_unique_creator_slug(
    conn,
    name: str,
    preferred_slug: Optional[str] = None,
    exclude_creator_id: Optional[str] = None,
) -> str:
    base = _normalize_creator_slug(preferred_slug or name or "criador")
    slug = base
    counter = 2
    while _creator_slug_exists(conn, slug, exclude_creator_id=exclude_creator_id):
        suffix = f"-{counter}"
        budget = max(1, 80 - len(suffix))
        slug = f"{base[:budget].rstrip('-')}{suffix}"
        counter += 1
    return slug


def _backfill_creator_slugs(conn) -> None:
    rows = conn.execute(
        "SELECT creator_id, name, slug FROM creators ORDER BY created_at ASC, name ASC"
    ).fetchall()
    for row in rows:
        creator_id = str(row["creator_id"])
        current_slug = str(row["slug"] or "").strip()
        normalized = _normalize_creator_slug(current_slug or row["name"] or "criador")
        needs_update = not current_slug or current_slug != normalized or _creator_slug_exists(
            conn,
            normalized,
            exclude_creator_id=creator_id,
        )
        if not needs_update:
            continue
        slug = _ensure_unique_creator_slug(
            conn,
            row["name"] or "criador",
            preferred_slug=current_slug or normalized,
            exclude_creator_id=creator_id,
        )
        conn.execute(
            "UPDATE creators SET slug=?, updated_at=? WHERE creator_id=?",
            (slug, datetime.now(timezone.utc).isoformat(), creator_id),
        )

@_sqlite_retry
def creator_create(data: Dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO creators
              (creator_id, name, slug, real_name, email, phone, whatsapp, status,
               logo_b64, logo_position, logo_opacity,
               commission_model, commission_pct, fixed_monthly,
               content_language, notification_email, notification_whatsapp,
               trend_report_frequency, drive_folder_id, drive_service_account,
               portal_branding, default_edit_config, reference_channels, preferred_categories,
               preferred_tags, notes, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data["creator_id"], data["name"], data.get("slug"), data.get("real_name"),
            data["email"], data.get("phone"), data.get("whatsapp"),
            data.get("status", "trial"),
            data.get("logo_b64"), data.get("logo_position", "bottom-right"),
            data.get("logo_opacity", 0.7),
            data.get("commission_model", "percentage"),
            data.get("commission_pct", 25.0),
            data.get("fixed_monthly", 0.0),
            data.get("content_language", "pt-BR"),
            1 if data.get("notification_email", True) else 0,
            1 if data.get("notification_whatsapp", False) else 0,
            data.get("trend_report_frequency", "weekly"),
            data.get("drive_folder_id"), data.get("drive_service_account"),
            json.dumps(data.get("portal_branding", {}), ensure_ascii=False),
            json.dumps(data.get("default_edit_config", {}), ensure_ascii=False),
            json.dumps(data.get("reference_channels", []), ensure_ascii=False),
            json.dumps(data.get("preferred_categories", []), ensure_ascii=False),
            json.dumps(data.get("preferred_tags", []), ensure_ascii=False),
            data.get("notes"),
            data["created_at"], data["updated_at"],
        ))


@_sqlite_retry
def creator_list(status: Optional[str] = None, limit: int = 100) -> List[Dict]:
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM creators WHERE status=? ORDER BY name LIMIT ?", (status, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM creators ORDER BY name LIMIT ?", (limit,)
            ).fetchall()
        return [_creator_row(r) for r in rows]


@_sqlite_retry
def creator_get(creator_id: str) -> Optional[Dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM creators WHERE creator_id=?", (creator_id,)).fetchone()
        if not row:
            return None
        c = _creator_row(row)
        # Attach platforms
        prows = conn.execute(
            "SELECT * FROM platform_accounts WHERE creator_id=?", (creator_id,)
        ).fetchall()
        c["platforms"] = [_platform_row(p) for p in prows]
        return c


@_sqlite_retry
def creator_get_by_slug(slug: str) -> Optional[Dict]:
    normalized = _normalize_creator_slug(slug or "")
    if not normalized:
        return None
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM creators WHERE slug=?", (normalized,)).fetchone()
        if not row:
            return None
        creator_id = str(row["creator_id"])
    return creator_get(creator_id)


@_sqlite_retry
def creator_resolve_slug(
    name: str,
    preferred_slug: Optional[str] = None,
    exclude_creator_id: Optional[str] = None,
) -> str:
    with get_conn() as conn:
        return _ensure_unique_creator_slug(
            conn,
            name=name,
            preferred_slug=preferred_slug,
            exclude_creator_id=exclude_creator_id,
        )


@_sqlite_retry
def creator_update(creator_id: str, updates: Dict[str, Any]) -> bool:
    if not updates:
        return True
    json_fields = {"portal_branding", "default_edit_config", "reference_channels", "preferred_categories", "preferred_tags", "own_channel_urls", "filming_setups", "location_types"}
    bool_fields = {"notification_email", "notification_whatsapp"}
    set_clauses = []
    values = []
    for k, v in updates.items():
        if k in json_fields:
            set_clauses.append(f"{k}=?")
            values.append(json.dumps(v, ensure_ascii=False))
        elif k in bool_fields:
            set_clauses.append(f"{k}=?")
            values.append(1 if v else 0)
        else:
            set_clauses.append(f"{k}=?")
            values.append(v)
    set_clauses.append("updated_at=?")
    values.append(datetime.now(timezone.utc).isoformat())
    values.append(creator_id)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE creators SET {', '.join(set_clauses)} WHERE creator_id=?", values
        )
    return True


@_sqlite_retry
def creator_delete(creator_id: str) -> bool:
    """Soft delete — sets status to churned."""
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE creators SET status='churned', updated_at=? WHERE creator_id=?",
            (now, creator_id)
        )
    return True


def _creator_row(row) -> Dict:
    d = dict(row)
    for field in ("portal_branding", "default_edit_config", "reference_channels", "preferred_categories", "preferred_tags", "own_channel_urls", "filming_setups", "location_types"):
        try:
            if field in {"portal_branding", "default_edit_config"}:
                d[field] = json.loads(d.get(field) or "{}")
            else:
                d[field] = json.loads(d.get(field) or "[]")
        except Exception:
            d[field] = {} if field in {"portal_branding", "default_edit_config"} else []
    d["notification_email"] = bool(d.get("notification_email", 1))
    d["notification_whatsapp"] = bool(d.get("notification_whatsapp", 0))
    return d


# ─────────────────────────────────────────────────────────────────────────────
# Platform accounts
# ─────────────────────────────────────────────────────────────────────────────

@_sqlite_retry
def platform_account_upsert(creator_id: str, data: Dict[str, Any]) -> None:
    import uuid as _uuid
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM platform_accounts WHERE creator_id=? AND platform=?",
            (creator_id, data["platform"])
        ).fetchone()
        if existing:
            conn.execute("""
                UPDATE platform_accounts
                SET username=?, profile_url=?, cookies_json=?,
                    is_verified=?, partner_program=?, status=?,
                    last_login_check=?
                WHERE creator_id=? AND platform=?
            """, (
                data["username"], data.get("profile_url"),
                data.get("cookies_json"),
                1 if data.get("is_verified") else 0,
                1 if data.get("partner_program") else 0,
                data.get("status", "active"),
                data.get("last_login_check"),
                creator_id, data["platform"],
            ))
        else:
            conn.execute("""
                INSERT INTO platform_accounts
                  (id, creator_id, platform, username, profile_url, cookies_json,
                   is_verified, partner_program, status, last_login_check)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                str(_uuid.uuid4()), creator_id, data["platform"],
                data["username"], data.get("profile_url"), data.get("cookies_json"),
                1 if data.get("is_verified") else 0,
                1 if data.get("partner_program") else 0,
                data.get("status", "active"), data.get("last_login_check"),
            ))


@_sqlite_retry
def platform_account_delete(creator_id: str, platform: str) -> bool:
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM platform_accounts WHERE creator_id=? AND platform=?",
            (creator_id, platform)
        )
    return True


@_sqlite_retry
def platform_account_get(creator_id: str, platform: str) -> Optional[Dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM platform_accounts WHERE creator_id=? AND platform=?",
            (creator_id, platform)
        ).fetchone()
        return _platform_row(row) if row else None


def _platform_row(row) -> Dict:
    d = dict(row)
    d["is_verified"] = bool(d.get("is_verified", 0))
    d["partner_program"] = bool(d.get("partner_program", 0))
    # NEVER expose cookies_json in API — replace with status hint
    d.pop("cookies_json", None)
    return d


def _platform_row_with_cookies(row) -> Dict:
    """For internal use only (publish pipeline)."""
    d = dict(row)
    d["is_verified"] = bool(d.get("is_verified", 0))
    d["partner_program"] = bool(d.get("partner_program", 0))
    return d


@_sqlite_retry
def platform_account_get_with_cookies(creator_id: str, platform: str) -> Optional[Dict]:
    """Internal use — returns cookies_json (encrypted)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM platform_accounts WHERE creator_id=? AND platform=?",
            (creator_id, platform)
        ).fetchone()
        return _platform_row_with_cookies(row) if row else None


@_sqlite_retry
def platform_account_update_login_check(creator_id: str, platform: str, status: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute("""
            UPDATE platform_accounts
            SET last_login_check=?, status=?
            WHERE creator_id=? AND platform=?
        """, (now, status, creator_id, platform))


# ─────────────────────────────────────────────────────────────────────────────
# Publish jobs
# ─────────────────────────────────────────────────────────────────────────────

@_sqlite_retry
def publish_job_create(data: Dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO publish_jobs
              (job_id, creator_id, video_object_key, thumbnail_object_key,
               platforms, metadata_json, schedule_at, status, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            data["job_id"], data["creator_id"], data["video_object_key"],
            data.get("thumbnail_object_key"),
            json.dumps(data.get("platforms", []), ensure_ascii=False),
            json.dumps(data.get("metadata", {}), ensure_ascii=False),
            data.get("schedule_at"), data.get("status", "pending"),
            data["created_at"], data["updated_at"],
        ))


@_sqlite_retry
def publish_job_get(job_id: str) -> Optional[Dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM publish_jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["platforms"] = json.loads(d.get("platforms") or "[]")
        d["metadata"] = json.loads(d.get("metadata_json") or "{}")
        return d


@_sqlite_retry
def publish_job_update_status(job_id: str, status: str, *, detail: str = "", progress_pct: int = -1) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        if progress_pct >= 0:
            conn.execute(
                "UPDATE publish_jobs SET status=?, detail=?, progress_pct=?, updated_at=? WHERE job_id=?",
                (status, detail, progress_pct, now, job_id)
            )
        elif detail:
            conn.execute(
                "UPDATE publish_jobs SET status=?, detail=?, updated_at=? WHERE job_id=?",
                (status, detail, now, job_id)
            )
        else:
            conn.execute(
                "UPDATE publish_jobs SET status=?, updated_at=? WHERE job_id=?",
                (status, now, job_id)
            )


@_sqlite_retry
def publication_create(data: Dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO publications
              (pub_id, job_id, creator_id, platform, status,
               video_url, video_id_platform, error_msg, screenshot_path,
               created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data["pub_id"], data["job_id"], data["creator_id"], data["platform"],
            data.get("status", "queued"), None, None, None, None,
            data["created_at"], data["updated_at"],
        ))


@_sqlite_retry
def publication_update(pub_id: str, updates: Dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    set_parts = [f"{k}=?" for k in updates]
    set_parts.append("updated_at=?")
    vals = list(updates.values()) + [now, pub_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE publications SET {', '.join(set_parts)} WHERE pub_id=?", vals)


@_sqlite_retry
def publications_by_job(job_id: str) -> List[Dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM publications WHERE job_id=?", (job_id,)).fetchall()
        return [dict(r) for r in rows]


@_sqlite_retry
def publications_by_creator(creator_id: str, limit: int = 100) -> List[Dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM publications WHERE creator_id=? ORDER BY created_at DESC LIMIT ?",
            (creator_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Social Integration Layer
# ─────────────────────────────────────────────────────────────────────────────

def _social_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _social_uuid() -> str:
    return str(uuid.uuid4())


def _json_or(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value or "")
    except Exception:
        return default


def _social_connection_row(row) -> Dict:
    d = dict(row)
    d["scopes"] = _json_or(d.get("scopes"), [])
    d["metadata"] = _json_or(d.get("metadata_json"), {})
    d.pop("metadata_json", None)
    return d


def _social_channel_row(row) -> Dict:
    d = dict(row)
    d["metadata"] = _json_or(d.get("metadata_json"), {})
    d.pop("metadata_json", None)
    return d


def _social_asset_row(row) -> Dict:
    return dict(row)


def _social_post_row(row) -> Dict:
    d = dict(row)
    d["metadata"] = _json_or(d.get("metadata_json"), {})
    d.pop("metadata_json", None)
    return d


@_sqlite_retry
def social_connection_create(data: Dict[str, Any]) -> Dict:
    now = _social_now()
    conn_id = data.get("id") or _social_uuid()
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO social_connections
              (id, user_id, brand_id, provider, platform,
               external_account_id, external_account_name,
               composio_entity_id, composio_connection_id,
               status, scopes, metadata_json, created_at, updated_at, last_sync_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            conn_id,
            data.get("user_id") or "api",
            data["brand_id"],
            data.get("provider") or "composio",
            data["platform"],
            data.get("external_account_id"),
            data.get("external_account_name"),
            data.get("composio_entity_id"),
            data.get("composio_connection_id"),
            data.get("status") or "connected",
            json.dumps(data.get("scopes") or [], ensure_ascii=False),
            json.dumps(data.get("metadata") or {}, ensure_ascii=False),
            data.get("created_at") or now,
            data.get("updated_at") or now,
            data.get("last_sync_at"),
        ))
    return social_connection_get(conn_id) or {"id": conn_id}


@_sqlite_retry
def social_connection_upsert(data: Dict[str, Any]) -> Dict:
    comp_id = data.get("composio_connection_id")
    existing = None
    with get_conn() as conn:
        if comp_id:
            existing = conn.execute(
                "SELECT id FROM social_connections WHERE composio_connection_id=?",
                (comp_id,),
            ).fetchone()
    if existing:
        social_connection_update(existing["id"], data)
        return social_connection_get(existing["id"]) or {"id": existing["id"]}
    return social_connection_create(data)


@_sqlite_retry
def social_connection_get(connection_id: str) -> Optional[Dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM social_connections WHERE id=?", (connection_id,)).fetchone()
        return _social_connection_row(row) if row else None


@_sqlite_retry
def social_connection_get_by_composio(composio_connection_id: str) -> Optional[Dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM social_connections WHERE composio_connection_id=?",
            (composio_connection_id,),
        ).fetchone()
        return _social_connection_row(row) if row else None


@_sqlite_retry
def social_connection_list(
    brand_id: Optional[str] = None,
    platform: Optional[str] = None,
    include_revoked: bool = False,
    limit: int = 200,
) -> List[Dict]:
    clauses, params = [], []
    if brand_id:
        clauses.append("brand_id=?")
        params.append(brand_id)
    if platform:
        clauses.append("platform=?")
        params.append(platform)
    if not include_revoked:
        clauses.append("status!='revoked'")
    q = "SELECT * FROM social_connections"
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(q, params).fetchall()
        return [_social_connection_row(r) for r in rows]


@_sqlite_retry
def social_connection_update(connection_id: str, updates: Dict[str, Any]) -> bool:
    allowed = {
        "user_id", "brand_id", "provider", "platform", "external_account_id",
        "external_account_name", "composio_entity_id", "composio_connection_id",
        "status", "scopes", "metadata", "last_sync_at",
    }
    fields, values = [], []
    for key, value in updates.items():
        if key not in allowed:
            continue
        col = "metadata_json" if key == "metadata" else key
        fields.append(f"{col}=?")
        if key in {"scopes", "metadata"}:
            values.append(json.dumps(value or ([] if key == "scopes" else {}), ensure_ascii=False))
        else:
            values.append(value)
    if not fields:
        return False
    fields.append("updated_at=?")
    values.extend([_social_now(), connection_id])
    with get_conn() as conn:
        cur = conn.execute(f"UPDATE social_connections SET {', '.join(fields)} WHERE id=?", values)
        return cur.rowcount > 0


@_sqlite_retry
def social_connection_revoke(connection_id: str) -> bool:
    return social_connection_update(connection_id, {"status": "revoked", "last_sync_at": _social_now()})


@_sqlite_retry
def social_post_create(data: Dict[str, Any]) -> Dict:
    now = _social_now()
    post_id = data.get("id") or _social_uuid()
    assets = data.get("assets") or []
    channels = data.get("channels") or []
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO social_posts
              (id, user_id, brand_id, source_post_id, title, caption, content_type,
               status, scheduled_at, published_at, metadata_json, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            post_id,
            data.get("user_id") or "api",
            data["brand_id"],
            data.get("source_post_id"),
            data.get("title"),
            data.get("caption") or "",
            data.get("content_type") or "text",
            data.get("status") or "draft",
            data.get("scheduled_at"),
            data.get("published_at"),
            json.dumps(data.get("metadata") or {}, ensure_ascii=False),
            data.get("created_at") or now,
            data.get("updated_at") or now,
        ))
        for asset in assets:
            conn.execute("""
                INSERT INTO social_post_assets
                  (id, post_id, asset_type, asset_url, storage_provider,
                   mime_type, size_bytes, width, height, duration_seconds, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                asset.get("id") or _social_uuid(),
                post_id,
                asset.get("asset_type") or asset.get("type") or "image",
                asset.get("asset_url") or asset.get("url") or "",
                asset.get("storage_provider"),
                asset.get("mime_type"),
                asset.get("size_bytes"),
                asset.get("width"),
                asset.get("height"),
                asset.get("duration_seconds"),
                now,
            ))
        for channel in channels:
            conn.execute("""
                INSERT INTO social_post_channels
                  (id, post_id, social_connection_id, platform, status,
                   external_post_id, external_post_url, error_message,
                   retry_count, metadata_json, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                channel.get("id") or _social_uuid(),
                post_id,
                channel["social_connection_id"],
                channel["platform"],
                channel.get("status") or "pending",
                channel.get("external_post_id"),
                channel.get("external_post_url"),
                channel.get("error_message"),
                int(channel.get("retry_count") or 0),
                json.dumps(channel.get("metadata") or {}, ensure_ascii=False),
                now,
                now,
            ))
    return social_post_get(post_id) or {"id": post_id}


@_sqlite_retry
def social_post_get(post_id: str, include_logs: bool = True) -> Optional[Dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM social_posts WHERE id=?", (post_id,)).fetchone()
        if not row:
            return None
        post = _social_post_row(row)
        assets = conn.execute(
            "SELECT * FROM social_post_assets WHERE post_id=? ORDER BY created_at ASC",
            (post_id,),
        ).fetchall()
        channels = conn.execute("""
            SELECT ch.*, sc.external_account_name, sc.status AS connection_status,
                   sc.composio_connection_id
            FROM social_post_channels ch
            LEFT JOIN social_connections sc ON sc.id = ch.social_connection_id
            WHERE ch.post_id=?
            ORDER BY ch.created_at ASC
        """, (post_id,)).fetchall()
        post["assets"] = [_social_asset_row(a) for a in assets]
        post["channels"] = [_social_channel_row(c) for c in channels]
        if include_logs:
            logs = conn.execute(
                "SELECT * FROM social_post_logs WHERE post_id=? ORDER BY created_at ASC LIMIT 300",
                (post_id,),
            ).fetchall()
            post["logs"] = [dict(r) | {"payload": _json_or(dict(r).get("payload_json"), {})} for r in logs]
        return post


@_sqlite_retry
def social_post_list(
    brand_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
    clauses, params = [], []
    if brand_id:
        clauses.append("brand_id=?")
        params.append(brand_id)
    if status:
        clauses.append("status=?")
        params.append(status)
    q = "SELECT * FROM social_posts"
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(q, params).fetchall()
    return [social_post_get(r["id"], include_logs=False) for r in rows]


@_sqlite_retry
def social_post_due(now_iso: str, limit: int = 25) -> List[Dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM social_posts
            WHERE status='scheduled' AND scheduled_at IS NOT NULL AND scheduled_at<=?
            ORDER BY scheduled_at ASC LIMIT ?
        """, (now_iso, limit)).fetchall()
    return [_social_post_row(r) for r in rows]


@_sqlite_retry
def social_post_update(post_id: str, updates: Dict[str, Any]) -> bool:
    allowed = {"title", "caption", "content_type", "status", "scheduled_at", "published_at", "metadata"}
    fields, values = [], []
    for key, value in updates.items():
        if key not in allowed:
            continue
        col = "metadata_json" if key == "metadata" else key
        fields.append(f"{col}=?")
        values.append(json.dumps(value or {}, ensure_ascii=False) if key == "metadata" else value)
    if not fields:
        return False
    fields.append("updated_at=?")
    values.extend([_social_now(), post_id])
    with get_conn() as conn:
        cur = conn.execute(f"UPDATE social_posts SET {', '.join(fields)} WHERE id=?", values)
        return cur.rowcount > 0


@_sqlite_retry
def social_post_acquire_for_publish(post_id: str, from_statuses: Optional[List[str]] = None) -> bool:
    statuses = from_statuses or ["approved", "scheduled"]
    placeholders = ",".join("?" * len(statuses))
    now = _social_now()
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE social_posts SET status='publishing', updated_at=? WHERE id=? AND status IN ({placeholders})",
            [now, post_id] + statuses,
        )
        return cur.rowcount == 1


@_sqlite_retry
def social_channel_update(channel_id: str, updates: Dict[str, Any]) -> bool:
    allowed = {
        "status", "external_post_id", "external_post_url", "error_message",
        "retry_count", "metadata",
    }
    fields, values = [], []
    for key, value in updates.items():
        if key not in allowed:
            continue
        col = "metadata_json" if key == "metadata" else key
        fields.append(f"{col}=?")
        values.append(json.dumps(value or {}, ensure_ascii=False) if key == "metadata" else value)
    if not fields:
        return False
    fields.append("updated_at=?")
    values.extend([_social_now(), channel_id])
    with get_conn() as conn:
        cur = conn.execute(f"UPDATE social_post_channels SET {', '.join(fields)} WHERE id=?", values)
        return cur.rowcount > 0


@_sqlite_retry
def social_post_log_create(
    post_id: str,
    message: str,
    *,
    channel_id: Optional[str] = None,
    level: str = "info",
    payload: Optional[Dict[str, Any]] = None,
) -> Dict:
    log_id = _social_uuid()
    now = _social_now()
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO social_post_logs
              (id, post_id, social_post_channel_id, level, message, payload_json, created_at)
            VALUES (?,?,?,?,?,?,?)
        """, (
            log_id,
            post_id,
            channel_id,
            level,
            message,
            json.dumps(payload or {}, ensure_ascii=False),
            now,
        ))
    return {"id": log_id, "post_id": post_id, "channel_id": channel_id, "level": level, "message": message, "created_at": now}


@_sqlite_retry
def social_post_finalize(post_id: str) -> Optional[Dict]:
    post = social_post_get(post_id, include_logs=False)
    if not post:
        return None
    channels = post.get("channels") or []
    statuses = [c.get("status") for c in channels]
    now = _social_now()
    if statuses and all(s == "published" for s in statuses):
        social_post_update(post_id, {"status": "published", "published_at": now})
    elif statuses and any(s == "published" for s in statuses):
        social_post_update(post_id, {"status": "partial_failed"})
    else:
        social_post_update(post_id, {"status": "failed"})
    return social_post_get(post_id)


# ─────────────────────────────────────────────────────────────────────────────
# Selector maps
# ─────────────────────────────────────────────────────────────────────────────

@_sqlite_retry
def selector_map_get(platform: str) -> Optional[Dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM selector_maps WHERE platform=?", (platform,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["selectors"] = json.loads(d.get("data_json") or "{}")
        return d


@_sqlite_retry
def selector_map_upsert(platform: str, version: str, selectors: Dict) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO selector_maps (platform, version, data_json)
            VALUES (?,?,?)
            ON CONFLICT(platform) DO UPDATE SET version=excluded.version, data_json=excluded.data_json
        """, (platform, version, json.dumps(selectors, ensure_ascii=False)))


# ─────────────────────────────────────────────────────────────────────────────
# Trends
# ─────────────────────────────────────────────────────────────────────────────

@_sqlite_retry
def trend_raw_insert(data: Dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO trends_raw (id, platform, collected_at, data_type, data_json)
            VALUES (?,?,?,?,?)
        """, (
            data["id"], data["platform"], data["collected_at"],
            data["data_type"], json.dumps(data.get("data", {}), ensure_ascii=False)
        ))


@_sqlite_retry
def trend_raw_list(platform: Optional[str] = None, data_type: Optional[str] = None,
                   limit: int = 200) -> List[Dict]:
    with get_conn() as conn:
        q = "SELECT * FROM trends_raw"
        params: list = []
        clauses = []
        if platform:
            clauses.append("platform=?")
            params.append(platform)
        if data_type:
            clauses.append("data_type=?")
            params.append(data_type)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY collected_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(q, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["data"] = json.loads(d.get("data_json") or "{}")
            except Exception:
                d["data"] = {}
            result.append(d)
        return result


@_sqlite_retry
def trend_channel_videos_for_creator(creator_id: str, limit: int = 100) -> List[Dict]:
    """Return channel_video records collected for a specific creator, newest first."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM trends_raw
               WHERE data_type='channel_video'
                 AND json_extract(data_json,'$.creator_id')=?
               ORDER BY collected_at DESC LIMIT ?""",
            (creator_id, limit),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["data"] = json.loads(d.get("data_json") or "{}")
        except Exception:
            d["data"] = {}
        result.append(d)
    return result


@_sqlite_retry
def briefing_create(data: Dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO trend_briefings
              (briefing_id, creator_id, content_json, generated_at,
               sent_email, sent_whatsapp)
            VALUES (?,?,?,?,0,0)
        """, (
            data["briefing_id"], data["creator_id"],
            json.dumps(data.get("content", {}), ensure_ascii=False),
            data["generated_at"],
        ))


@_sqlite_retry
def briefing_list(creator_id: Optional[str] = None, limit: int = 50) -> List[Dict]:
    with get_conn() as conn:
        if creator_id:
            rows = conn.execute(
                "SELECT * FROM trend_briefings WHERE creator_id=? ORDER BY generated_at DESC LIMIT ?",
                (creator_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trend_briefings ORDER BY generated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["content"] = json.loads(d.get("content_json") or "{}")
            except Exception:
                d["content"] = {}
            result.append(d)
        return result


@_sqlite_retry
def briefing_get(briefing_id: str) -> Optional[Dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM trend_briefings WHERE briefing_id=?", (briefing_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["content"] = json.loads(d.get("content_json") or "{}")
        except Exception:
            d["content"] = {}
        return d


@_sqlite_retry
def briefing_mark_sent(briefing_id: str, channel: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        if channel == "email":
            conn.execute(
                "UPDATE trend_briefings SET sent_email=1, email_sent_at=? WHERE briefing_id=?",
                (now, briefing_id)
            )
        elif channel == "whatsapp":
            conn.execute(
                "UPDATE trend_briefings SET sent_whatsapp=1, whatsapp_sent_at=? WHERE briefing_id=?",
                (now, briefing_id)
            )


# ─────────────────────────────────────────────────────────────────────────────
# DMCA
# ─────────────────────────────────────────────────────────────────────────────

@_sqlite_retry
def dmca_create(data: Dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO dmca_infringements
              (infringement_id, creator_id, original_video_id, original_url,
               infringing_url, infringing_site, detection_method,
               confidence, status, notes, detected_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data["infringement_id"], data["creator_id"], data.get("original_video_id"),
            data["original_url"], data["infringing_url"], data["infringing_site"],
            data["detection_method"], data.get("confidence", 0.0),
            data.get("status", "detected"), data.get("notes", ""),
            data["detected_at"],
        ))


@_sqlite_retry
def dmca_list(creator_id: Optional[str] = None, status: Optional[str] = None,
              limit: int = 200) -> List[Dict]:
    with get_conn() as conn:
        clauses, params = [], []
        if creator_id:
            clauses.append("creator_id=?")
            params.append(creator_id)
        if status:
            clauses.append("status=?")
            params.append(status)
        q = "SELECT * FROM dmca_infringements"
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY detected_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in conn.execute(q, params).fetchall()]


@_sqlite_retry
def dmca_update_status(infringement_id: str, status: str, extra: Optional[Dict] = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    updates = {"status": status}
    if status == "takedown_sent":
        updates["takedown_sent_at"] = now
    elif status == "removed":
        updates["removed_at"] = now
    if extra:
        updates.update(extra)
    set_parts = [f"{k}=?" for k in updates]
    vals = list(updates.values()) + [infringement_id]
    with get_conn() as conn:
        conn.execute(
            f"UPDATE dmca_infringements SET {', '.join(set_parts)} WHERE infringement_id=?", vals
        )


@_sqlite_retry
def dmca_stats(creator_id: Optional[str] = None) -> Dict:
    with get_conn() as conn:
        base = "SELECT status, COUNT(*) as cnt FROM dmca_infringements"
        params: list = []
        if creator_id:
            base += " WHERE creator_id=?"
            params.append(creator_id)
        base += " GROUP BY status"
        rows = conn.execute(base, params).fetchall()
        counts = {r["status"]: r["cnt"] for r in rows}
        total = sum(counts.values())
        pending = counts.get("detected", 0)
        return {
            "total_detected": total,
            "total_takedown_sent": counts.get("takedown_sent", 0),
            "total_removed": counts.get("removed", 0),
            "total_ignored": counts.get("ignored", 0),
            "total_failed": counts.get("failed", 0),
            "pending_action": pending,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Calendar
# ─────────────────────────────────────────────────────────────────────────────

@_sqlite_retry
def calendar_create(data: Dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO calendar_entries
              (entry_id, creator_id, video_object_key, run_id,
               publish_platforms, publish_at, published, publish_results,
               cross_promote, cross_channels, cross_promote_at, cross_results,
               title, description, tags, category, status, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data["entry_id"], data["creator_id"], data["video_object_key"],
            data.get("run_id"),
            json.dumps(data.get("publish_platforms", []), ensure_ascii=False),
            data["publish_at"],
            1 if data.get("published") else 0,
            json.dumps(data.get("publish_results", {}), ensure_ascii=False),
            1 if data.get("cross_promote", True) else 0,
            json.dumps(data.get("cross_channels", []), ensure_ascii=False),
            data.get("cross_promote_at"),
            json.dumps(data.get("cross_results", {}), ensure_ascii=False),
            data.get("title", ""), data.get("description", ""),
            json.dumps(data.get("tags", []), ensure_ascii=False),
            data.get("category", "Amateur"),
            data.get("status", "scheduled"),
            data["created_at"], data["updated_at"],
        ))


@_sqlite_retry
def calendar_list(creator_id: Optional[str] = None, status: Optional[str] = None,
                  from_dt: Optional[str] = None, to_dt: Optional[str] = None,
                  limit: int = 100) -> List[Dict]:
    with get_conn() as conn:
        clauses, params = [], []
        if creator_id:
            clauses.append("creator_id=?")
            params.append(creator_id)
        if status:
            clauses.append("status=?")
            params.append(status)
        if from_dt:
            clauses.append("publish_at>=?")
            params.append(from_dt)
        if to_dt:
            clauses.append("publish_at<=?")
            params.append(to_dt)
        q = "SELECT * FROM calendar_entries"
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY publish_at ASC LIMIT ?"
        params.append(limit)
        return [_calendar_row(r) for r in conn.execute(q, params).fetchall()]


@_sqlite_retry
def calendar_get(entry_id: str) -> Optional[Dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM calendar_entries WHERE entry_id=?", (entry_id,)).fetchone()
        return _calendar_row(row) if row else None


@_sqlite_retry
def calendar_update(entry_id: str, updates: Dict[str, Any]) -> None:
    json_fields = {"publish_platforms", "publish_results", "cross_channels", "cross_results", "tags"}
    bool_fields = {"published", "cross_promote"}
    now = datetime.now(timezone.utc).isoformat()
    set_parts, vals = [], []
    for k, v in updates.items():
        set_parts.append(f"{k}=?")
        if k in json_fields:
            vals.append(json.dumps(v, ensure_ascii=False))
        elif k in bool_fields:
            vals.append(1 if v else 0)
        else:
            vals.append(v)
    set_parts.append("updated_at=?")
    vals.append(now)
    vals.append(entry_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE calendar_entries SET {', '.join(set_parts)} WHERE entry_id=?", vals)


@_sqlite_retry
def calendar_delete(entry_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM calendar_entries WHERE entry_id=?", (entry_id,))


@_sqlite_retry
def calendar_due(now_iso: str) -> List[Dict]:
    """Return scheduled entries with publish_at <= now."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM calendar_entries WHERE status='scheduled' AND publish_at<=? LIMIT 50",
            (now_iso,)
        ).fetchall()
        return [_calendar_row(r) for r in rows]


def _calendar_row(row) -> Dict:
    d = dict(row)
    for f in ("publish_platforms", "cross_channels", "tags"):
        try:
            d[f] = json.loads(d.get(f) or "[]")
        except Exception:
            d[f] = []
    for f in ("publish_results", "cross_results"):
        try:
            d[f] = json.loads(d.get(f) or "{}")
        except Exception:
            d[f] = {}
    d["published"] = bool(d.get("published", 0))
    d["cross_promote"] = bool(d.get("cross_promote", 1))
    return d


# ─────────────────────────────────────────────────────────────────────────────
# Financial
# ─────────────────────────────────────────────────────────────────────────────

@_sqlite_retry
def earning_create(data: Dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO earning_records
              (record_id, creator_id, platform, period, video_id,
               gross_revenue, platform_fee, net_revenue,
               agency_commission, creator_payout, views_in_period,
               source, scraped_at, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            data["record_id"], data["creator_id"], data["platform"],
            data["period"], data.get("video_id"),
            data.get("gross_revenue", 0.0), data.get("platform_fee", 0.0),
            data.get("net_revenue", 0.0), data.get("agency_commission", 0.0),
            data.get("creator_payout", 0.0), data.get("views_in_period", 0),
            data.get("source", "manual"), data.get("scraped_at"),
            data["created_at"],
        ))


@_sqlite_retry
def earnings_list(creator_id: Optional[str] = None, period: Optional[str] = None,
                  limit: int = 200) -> List[Dict]:
    with get_conn() as conn:
        clauses, params = [], []
        if creator_id:
            clauses.append("creator_id=?")
            params.append(creator_id)
        if period:
            clauses.append("period=?")
            params.append(period)
        q = "SELECT * FROM earning_records"
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY period DESC, created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in conn.execute(q, params).fetchall()]


@_sqlite_retry
def earnings_report(creator_id: str, period: str, commission_pct: float = 25.0) -> Dict:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM earning_records WHERE creator_id=? AND period=?",
            (creator_id, period)
        ).fetchall()
    total_gross = 0.0
    total_platform_fee = 0.0
    total_net = 0.0
    total_agency = 0.0
    total_payout = 0.0
    total_views = 0
    by_platform: Dict[str, Dict] = {}

    for r in rows:
        d = dict(r)
        gross = float(d.get("gross_revenue") or 0)
        fee = float(d.get("platform_fee") or 0)
        net = gross - fee
        agency = net * (commission_pct / 100.0)
        payout = net - agency

        total_gross += gross
        total_platform_fee += fee
        total_net += net
        total_agency += agency
        total_payout += payout
        total_views += int(d.get("views_in_period") or 0)

        p = d["platform"]
        if p not in by_platform:
            by_platform[p] = {"gross": 0.0, "platform_fee": 0.0, "net": 0.0,
                               "agency": 0.0, "payout": 0.0, "views": 0}
        by_platform[p]["gross"] += gross
        by_platform[p]["platform_fee"] += fee
        by_platform[p]["net"] += net
        by_platform[p]["agency"] += agency
        by_platform[p]["payout"] += payout
        by_platform[p]["views"] += int(d.get("views_in_period") or 0)

    return {
        "creator_id": creator_id,
        "month": period,
        "total_gross": round(total_gross, 2),
        "total_platform_fees": round(total_platform_fee, 2),
        "total_net": round(total_net, 2),
        "total_agency_commission": round(total_agency, 2),
        "total_creator_payout": round(total_payout, 2),
        "total_views": total_views,
        "platforms_breakdown": by_platform,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@_sqlite_retry
def creator_stats_upsert(data: Dict[str, Any]) -> None:
    import uuid as _uuid
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO creator_stats
              (stat_id, creator_id, platform, scraped_at,
               total_views, subscribers, total_videos, earnings)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            str(_uuid.uuid4()), data["creator_id"], data["platform"],
            data["scraped_at"], data.get("total_views", 0),
            data.get("subscribers", 0), data.get("total_videos", 0),
            data.get("earnings", 0.0),
        ))


@_sqlite_retry
def creator_stats_latest(creator_id: str) -> List[Dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT cs.*
            FROM creator_stats cs
            INNER JOIN (
                SELECT platform, MAX(scraped_at) as max_at
                FROM creator_stats WHERE creator_id=?
                GROUP BY platform
            ) latest ON cs.platform=latest.platform AND cs.scraped_at=latest.max_at
            WHERE cs.creator_id=?
        """, (creator_id, creator_id)).fetchall()
        return [dict(r) for r in rows]
