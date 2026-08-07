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
import re
import time
import unicodedata
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
        _ensure_column("posts", "media_url", "media_url TEXT")

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

        # ── Products ────────────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id          TEXT PRIMARY KEY,
                company_id  TEXT NOT NULL,
                name        TEXT NOT NULL,
                slug        TEXT,
                description TEXT,
                category    TEXT,
                website     TEXT,
                socials     TEXT NOT NULL DEFAULT '{}',
                colors      TEXT NOT NULL DEFAULT '{}',
                active      INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_products_company ON products(company_id)")

        # ── Company assets (logos, references) ─────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS company_assets (
                id          TEXT PRIMARY KEY,
                company_id  TEXT NOT NULL,
                product_id  TEXT,
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
        # Ensure the column exists before indexing it (older DBs created company_assets
        # before product_id was introduced — indexing first would crash on those).
        _ensure_column("company_assets", "product_id", "product_id TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_product ON company_assets(product_id)")

        # ── Influencers (POR EMPRESA) — cadastro + dados; o banco de imagem fica em company_assets
        #    (kind='INFLUENCER_PHOTO', meta.influencer_id) → reusa o mesmo storage/upload das logos. ──
        conn.execute("""
            CREATE TABLE IF NOT EXISTS influencers (
                id          TEXT PRIMARY KEY,
                company_id  TEXT NOT NULL,
                name        TEXT NOT NULL,
                handle      TEXT,
                bio         TEXT,
                meta        TEXT NOT NULL DEFAULT '{}',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_influencers_company ON influencers(company_id)")

        # ── Empresa influencer (ex.: loucosdatelecom): INTERNA ou TERCEIRIZADA; @ + logo; tem influenciadores embaixo ──
        conn.execute("""
            CREATE TABLE IF NOT EXISTS influencer_companies (
                id          TEXT PRIMARY KEY,
                company_id  TEXT NOT NULL,
                name        TEXT NOT NULL,
                handle      TEXT,
                kind        TEXT DEFAULT 'external',
                website     TEXT,
                meta        TEXT NOT NULL DEFAULT '{}',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_infco_company ON influencer_companies(company_id)")

        # ── Eventos (cadastro p/ divulgação: data, local, descrição, logos, cores) ──
        #    logos do evento em company_assets (kind='EVENT_LOGO', meta.event_id). cores/extra no meta.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id          TEXT PRIMARY KEY,
                company_id  TEXT NOT NULL,
                name        TEXT NOT NULL,
                event_date  TEXT,
                location    TEXT,
                description TEXT,
                meta        TEXT NOT NULL DEFAULT '{}',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_company ON events(company_id)")

        # ── Empresa do evento (ORGANIZADOR, ex.: ExPSP) — IG + site + logo; tem vários eventos embaixo ──
        conn.execute("""
            CREATE TABLE IF NOT EXISTS event_organizers (
                id          TEXT PRIMARY KEY,
                company_id  TEXT NOT NULL,
                name        TEXT NOT NULL,
                instagram   TEXT,
                website     TEXT,
                meta        TEXT NOT NULL DEFAULT '{}',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_eventorg_company ON event_organizers(company_id)")

        # ── Solutions (Cliente → Produto → Solução) ─────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS solutions (
                id          TEXT PRIMARY KEY,
                company_id  TEXT NOT NULL,
                product_id  TEXT NOT NULL,
                name        TEXT NOT NULL,
                description TEXT,
                links       TEXT NOT NULL DEFAULT '[]',
                active      INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_solutions_product ON solutions(product_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_solutions_company ON solutions(company_id)")

        # ── Approval links (página pública de aprovação) ────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS approval_links (
                token       TEXT PRIMARY KEY,
                company_id  TEXT NOT NULL,
                post_ids    TEXT NOT NULL DEFAULT '[]',
                stage       TEXT NOT NULL DEFAULT 'client',
                status      TEXT NOT NULL DEFAULT 'open',
                created_at  TEXT NOT NULL,
                expires_at  TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_approval_links_company ON approval_links(company_id)")

        # ── Notifications log ───────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notifications_log (
                id          TEXT PRIMARY KEY,
                company_id  TEXT,
                channel     TEXT NOT NULL,
                trigger     TEXT,
                recipient   TEXT,
                status      TEXT NOT NULL DEFAULT 'sent',
                detail      TEXT,
                created_at  TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notif_company ON notifications_log(company_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS cost_log (
                id          TEXT PRIMARY KEY,
                company_id  TEXT,
                kind        TEXT,
                model       TEXT,
                cost_usd    REAL DEFAULT 0,
                created_at  TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cost_company ON cost_log(company_id)")

        # Briefing/positioning fields (added later; tables already exist on prod).
        _ensure_column("products", "objective", "objective TEXT")
        _ensure_column("products", "functions", "functions TEXT")
        _ensure_column("products", "knowledge", "knowledge TEXT")   # base de conhecimento (PDF/TXT extraído) p/ briefing rico
        _ensure_column("products", "web_brief", "web_brief TEXT")        # CACHE da pesquisa web (não busca ao vivo no request)
        _ensure_column("products", "web_brief_at", "web_brief_at TEXT")  # quando o cache web foi atualizado
        _ensure_column("brand_kits", "audience", "audience TEXT")
        _ensure_column("posts", "review_comment", "review_comment TEXT")
        _ensure_column("posts", "review_decision", "review_decision TEXT")
        _ensure_column("posts", "meta", "meta TEXT")                 # params de geração (regenerar c/ feedback)
        _ensure_column("posts", "reviewed_at", "reviewed_at TEXT")   # quando o cliente decidiu
        _ensure_column("brand_kits", "client_rules", "client_rules TEXT")  # aprendizado por cliente
        _ensure_column("brand_kits", "assuntos", "assuntos TEXT")  # pautas/temas cadastrados do cliente
        _ensure_column("brand_kits", "creative_config", "creative_config TEXT")  # prompts/design editáveis por cliente (JSON)
        _ensure_column("influencers", "infcompany_id", "infcompany_id TEXT")  # influencer pertence a uma EMPRESA influencer
        _ensure_column("events", "organizer_id", "organizer_id TEXT")  # evento pertence a um ORGANIZADOR
        _ensure_column("events", "date_start", "date_start TEXT")      # data de INÍCIO
        _ensure_column("events", "date_end", "date_end TEXT")          # data de FIM


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


def _slugify(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    slug = "".join(c if c.isalnum() or c == "-" else "-" for c in ascii_str.lower()).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "empresa"


def _brand_color_role(name: Any) -> str:
    compact = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    compact = re.sub(r"[^a-z0-9]+", "", compact)
    if compact in {"primary", "primarycolor", "primarycolour", "principal", "primaria", "corprincipal", "corprimaria"}:
        return "primary"
    if compact in {"secondary", "secondarycolor", "secondarycolour", "secundaria", "corsecundaria"}:
        return "secondary"
    if compact in {"accent", "accentcolor", "accentcolour", "destaque", "cordestaque"}:
        return "accent"
    return ""


def normalize_brand_colors(colors: Any) -> Dict[str, str]:
    """Keep the flexible palette contract while guaranteeing one canonical ``primary`` color.

    Empty palettes remain empty. Legacy aliases are canonicalized; when an old non-empty palette
    has no explicit primary, its accent (the old renderers' dominant choice) or first color is
    promoted deterministically. Only valid hex values survive and are stored as uppercase ``#RRGGBB``.
    """
    if not isinstance(colors, dict):
        return {}
    entries: List[tuple[str, str, str]] = []
    seen_names = set()
    for raw_name, raw_value in colors.items():
        name = str(raw_name or "").strip()
        value = str(raw_value or "").strip()
        if not name or not value:
            continue
        if re.fullmatch(r"#?[0-9a-fA-F]{3}", value):
            short = value.lstrip("#").upper()
            value = "#" + "".join(char * 2 for char in short)
        elif re.fullmatch(r"#?[0-9a-fA-F]{6}", value):
            value = "#" + value.lstrip("#").upper()
        else:
            # Renderizadores só entendem hexadecimal. Ignore lixo de respostas automáticas
            # antes de escolher a principal, para que uma cor válida restante possa ser promovida.
            continue
        role = _brand_color_role(name)
        canonical_name = role or name
        key = canonical_name.lower()
        if key in seen_names:
            continue
        seen_names.add(key)
        entries.append((canonical_name, value, role))
    if not entries:
        return {}

    primary_index = next((index for index, (_name, _value, role) in enumerate(entries) if role == "primary"), -1)
    if primary_index < 0:
        primary_index = next((index for index, (_name, _value, role) in enumerate(entries) if role == "accent"), 0)
    result: Dict[str, str] = {"primary": entries[primary_index][1]}
    for index, (name, value, role) in enumerate(entries):
        if index == primary_index or role == "primary":
            continue
        result[role or name] = value
    return result


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
            row["brand_kit"]["colors"] = normalize_brand_colors(
                json.loads(row["brand_kit"].get("colors") or "{}")
            )
            row["brand_kit"]["extras"] = json.loads(row["brand_kit"].get("extras") or "{}")
            try:
                row["brand_kit"]["creative_config"] = json.loads(row["brand_kit"].get("creative_config") or "{}")
            except Exception:
                row["brand_kit"]["creative_config"] = {}
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
    for key in ("name", "segment", "city", "state", "website", "phone", "email", "notes", "owner_user_id"):
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
        row["colors"] = normalize_brand_colors(json.loads(row.get("colors") or "{}"))
        row["extras"] = json.loads(row.get("extras") or "{}")
        try:
            row["creative_config"] = json.loads(row.get("creative_config") or "{}")
        except Exception:
            row["creative_config"] = {}
        return row


@_sqlite_retry
def brand_kit_upsert(company_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Atomically create or patch a brand kit, preserving every omitted field."""
    now = _now()
    scalar_columns = (
        "logo_url", "voice", "persona", "visual_prompt_base", "audience",
        "client_rules", "assuntos", "source",
    )
    insert_values: Dict[str, Any] = {
        "logo_url": data.get("logo_url"),
        "colors": json.dumps(normalize_brand_colors(data.get("colors") or {})),
        "voice": data.get("voice"),
        "persona": data.get("persona"),
        "visual_prompt_base": data.get("visual_prompt_base"),
        "extras": json.dumps(data.get("extras") or {}),
        "source": data.get("source") or "MANUAL",
        "audience": data.get("audience"),
        "client_rules": data.get("client_rules"),
        "assuntos": data.get("assuntos"),
        "creative_config": json.dumps(data.get("creative_config") or {}),
    }
    update_columns = [column for column in scalar_columns if column in data]
    update_columns += [column for column in ("colors", "extras", "creative_config") if column in data]
    assignments = [f"{column} = excluded.{column}" for column in update_columns]
    if assignments:
        assignments.append("updated_at = excluded.updated_at")
        conflict_sql = "DO UPDATE SET " + ", ".join(assignments)
    else:
        conflict_sql = "DO NOTHING"
    with get_conn() as conn:
        conn.execute(f"""
            INSERT INTO brand_kits (
                id, company_id, logo_url, colors, voice, persona, visual_prompt_base,
                extras, source, audience, client_rules, assuntos, creative_config,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(company_id) {conflict_sql}
        """, (
            _uuid(), company_id, insert_values["logo_url"], insert_values["colors"],
            insert_values["voice"], insert_values["persona"], insert_values["visual_prompt_base"],
            insert_values["extras"], insert_values["source"], insert_values["audience"],
            insert_values["client_rules"], insert_values["assuntos"],
            insert_values["creative_config"], now, now,
        ))
    return brand_kit_get(company_id)


@_sqlite_retry
def brand_kit_extras_patch(company_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Atomically replace named top-level extras namespaces without losing concurrent edits."""
    clean = {str(key): value for key, value in (patch or {}).items() if str(key)}
    if not clean:
        return brand_kit_get(company_id) or brand_kit_upsert(company_id, {})
    now = _now()
    initial_extras = json.dumps(clean)
    json_args: List[Any] = []
    setters = []
    for key, value in clean.items():
        setters.extend([f"$.{key}", json.dumps(value)])
    for index in range(0, len(setters), 2):
        json_args.extend((setters[index], setters[index + 1]))
    json_set_sql = ", ".join("?, json(?)" for _ in clean)
    with get_conn() as conn:
        conn.execute(f"""
            INSERT INTO brand_kits (
                id, company_id, colors, extras, source, creative_config, created_at, updated_at
            ) VALUES (?, ?, '{{}}', ?, 'MANUAL', '{{}}', ?, ?)
            ON CONFLICT(company_id) DO UPDATE SET
                extras = json_set(
                    CASE WHEN json_valid(brand_kits.extras) THEN brand_kits.extras ELSE '{{}}' END,
                    {json_set_sql}
                ),
                updated_at = excluded.updated_at
        """, (_uuid(), company_id, initial_extras, now, now, *json_args))
    return brand_kit_get(company_id)


@_sqlite_retry
def brand_kit_apply_auto(
    company_id: str,
    data: Dict[str, Any],
    *,
    replace_manual_palette: bool = False,
    replace_curated_fields: bool = False,
) -> Dict[str, Any]:
    """Apply detected fields without racing over edits marked as manual."""
    brand_kit_upsert(company_id, {})
    assignments: List[str] = []
    values: List[Any] = []
    extras_json = "CASE WHEN json_valid(extras) THEN extras ELSE '{}' END"
    for field in ("voice", "persona", "visual_prompt_base", "audience"):
        if field not in data:
            continue
        assignments.append(
            f"{field} = CASE WHEN ? OR NOT EXISTS ("
            f"SELECT 1 FROM json_each({extras_json}, '$.manual_fields') WHERE value = ?"
            f") THEN ? ELSE {field} END"
        )
        values.extend((1 if replace_curated_fields else 0, field, data[field]))
    if "colors" in data:
        palette_condition = (
            "? OR COALESCE(json_extract(" + extras_json
            + ", '$.palette_source'), '') NOT IN ('manual', 'legacy_preserved')"
        )
        assignments.append(
            "colors = CASE WHEN " + palette_condition + " THEN ? ELSE colors END"
        )
        values.extend((
            1 if replace_manual_palette else 0,
            json.dumps(normalize_brand_colors(data.get("colors") or {})),
        ))
        assignments.append(
            "extras = CASE WHEN " + palette_condition
            + " THEN json_set(" + extras_json + ", '$.palette_source', 'automatic') ELSE extras END"
        )
        values.append(1 if replace_manual_palette else 0)
    if not assignments:
        return brand_kit_get(company_id)
    assignments.append("updated_at = ?")
    values.extend((_now(), company_id))
    with get_conn() as conn:
        conn.execute(
            f"UPDATE brand_kits SET {', '.join(assignments)} WHERE company_id = ?",
            values,
        )
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


@_sqlite_retry
def competitor_update(competitor_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    fields = []
    values: List[Any] = []
    if "name" in data:
        fields.append("name = ?")
        values.append(data["name"])
    if "handles" in data:
        fields.append("handles = ?")
        values.append(json.dumps(data.get("handles") or {}))
    if "metrics" in data:
        fields.append("metrics = ?")
        values.append(json.dumps(data.get("metrics") or {}))
    if "dossier" in data:
        fields.append("dossier = ?")
        values.append(data.get("dossier"))
    if "last_analyzed_at" in data:
        fields.append("last_analyzed_at = ?")
        values.append(data.get("last_analyzed_at"))
    if not fields:
        return None
    values.append(competitor_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE competitors SET {', '.join(fields)} WHERE id = ?", values)
        row = conn.execute("SELECT * FROM competitors WHERE id = ?", (competitor_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["handles"] = json.loads(result.get("handles") or "{}")
        result["metrics"] = json.loads(result.get("metrics") or "{}")
        return result


# ─────────────────────────────────────────────────────────────────────────────
# Posts (approval workflow)
# ─────────────────────────────────────────────────────────────────────────────

POST_STATUSES = ["DRAFT", "REVIEW", "APPROVED", "SCHEDULED", "PUBLISHED", "FAILED"]

POST_TRANSITIONS = {
    "DRAFT": ["REVIEW"],
    "REVIEW": ["APPROVED", "DRAFT"],
    "APPROVED": ["SCHEDULED", "PUBLISHED", "REVIEW"],
    "SCHEDULED": ["PUBLISHED", "APPROVED"],
    "PUBLISHED": [],
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
            try:
                row["meta"] = json.loads(row.get("meta") or "{}")
            except Exception:
                row["meta"] = {}
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
        try:
            row["meta"] = json.loads(row.get("meta") or "{}")
        except Exception:
            row["meta"] = {}
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
    meta = json.dumps(data.get("meta") or {})
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO posts (id, company_id, status, title, copy, hashtags, networks, media_url, scheduled_at, published_at, postiz_id, error, meta, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (pid, data.get("company_id"), status, data.get("title"), data.get("copy"), hashtags, networks, data.get("media_url"), data.get("scheduled_at"), data.get("published_at"), data.get("postiz_id"), data.get("error"), meta, now, now))
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
        if to_status == "PUBLISHED":
            conn.execute("UPDATE posts SET status = ?, published_at = ?, updated_at = ? WHERE id = ?", (to_status, now, now, post_id))
        else:
            conn.execute("UPDATE posts SET status = ?, updated_at = ? WHERE id = ?", (to_status, now, post_id))
    return post_get(post_id)


@_sqlite_retry
def post_update(post_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    now = _now()
    fields = []
    values: List[Any] = []
    for key in ("title", "copy", "media_url", "scheduled_at", "published_at", "postiz_id", "error", "review_comment", "review_decision", "reviewed_at"):
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
            INSERT INTO company_assets (id, company_id, product_id, post_id, kind, source, url, meta, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (aid, company_id, data.get("product_id"), data.get("post_id"), data.get("kind", "IMAGE"), data.get("source", "UPLOADED"), data.get("url", ""), meta, now))
    return {"id": aid, "company_id": company_id, "product_id": data.get("product_id"), "kind": data.get("kind", "IMAGE"), "source": data.get("source", "UPLOADED"), "url": data.get("url", ""), "meta": data.get("meta") or {}}


@_sqlite_retry
def asset_delete(asset_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM company_assets WHERE id = ?", (asset_id,))
        return cur.rowcount > 0


@_sqlite_retry
def asset_get(asset_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM company_assets WHERE id = ?", (asset_id,)).fetchone()
        if not row:
            return None
        row = dict(row)
        row["meta"] = json.loads(row.get("meta") or "{}")
        return row


@_sqlite_retry
def asset_update_meta(asset_id: str, meta: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        conn.execute("UPDATE company_assets SET meta = ? WHERE id = ?", (json.dumps(meta), asset_id))
    return asset_get(asset_id)


@_sqlite_retry
def asset_list_logos(company_id: str, product_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all logo assets for a company (or specific product)."""
    with get_conn() as conn:
        if product_id:
            rows = conn.execute("""
                SELECT * FROM company_assets
                WHERE company_id = ? AND product_id = ? AND json_extract(meta, '$.role') = 'logo'
                ORDER BY created_at DESC
            """, (company_id, product_id)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM company_assets
                WHERE company_id = ? AND product_id IS NULL AND json_extract(meta, '$.role') = 'logo'
                ORDER BY created_at DESC
            """, (company_id,)).fetchall()
        results = []
        for r in rows:
            row = dict(r)
            row["meta"] = json.loads(row.get("meta") or "{}")
            results.append(row)
        return results


@_sqlite_retry
def asset_clear_primary(company_id: str, product_id: Optional[str] = None) -> None:
    """Clear is_primary flag on all logos of a company (or product)."""
    with get_conn() as conn:
        if product_id:
            rows = conn.execute("""
                SELECT id, meta FROM company_assets
                WHERE company_id = ? AND product_id = ? AND json_extract(meta, '$.role') = 'logo'
            """, (company_id, product_id)).fetchall()
        else:
            rows = conn.execute("""
                SELECT id, meta FROM company_assets
                WHERE company_id = ? AND product_id IS NULL AND json_extract(meta, '$.role') = 'logo'
            """, (company_id,)).fetchall()
        for r in rows:
            meta = json.loads(r["meta"] or "{}")
            if meta.get("is_primary"):
                meta["is_primary"] = 0
                conn.execute("UPDATE company_assets SET meta = ? WHERE id = ?", (json.dumps(meta), r["id"]))


@_sqlite_retry
def asset_set_primary_logo(
    company_id: str, asset_id: str, brand_source: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Atomically select one primary company logo and optionally sync the brand kit URL."""
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        target = conn.execute(
            """SELECT * FROM company_assets
               WHERE id = ? AND company_id = ? AND product_id IS NULL
                 AND json_extract(meta, '$.role') = 'logo'""",
            (asset_id, company_id),
        ).fetchone()
        if not target:
            return None
        conn.execute(
            """UPDATE company_assets
               SET meta = json_set(
                   CASE WHEN json_valid(meta) THEN meta ELSE '{}' END,
                   '$.is_primary', CASE WHEN id = ? THEN 1 ELSE 0 END
               )
               WHERE company_id = ? AND product_id IS NULL
                 AND json_extract(meta, '$.role') = 'logo'""",
            (asset_id, company_id),
        )
        if brand_source:
            now = _now()
            conn.execute("""
                INSERT INTO brand_kits (
                    id, company_id, logo_url, colors, extras, source, created_at, updated_at
                ) VALUES (?, ?, ?, '{}', '{}', ?, ?, ?)
                ON CONFLICT(company_id) DO UPDATE SET
                    logo_url = excluded.logo_url,
                    source = excluded.source,
                    updated_at = excluded.updated_at
            """, (_uuid(), company_id, target["url"], brand_source, now, now))
    return asset_get(asset_id)


@_sqlite_retry
def asset_claim_primary_logo_if_empty(company_id: str, asset_id: str, brand_source: str = "AUTO") -> bool:
    """Promote an imported logo only when no manual/concurrent primary already exists."""
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        target = conn.execute(
            """SELECT url FROM company_assets
               WHERE id = ? AND company_id = ? AND product_id IS NULL
                 AND json_extract(meta, '$.role') = 'logo'""",
            (asset_id, company_id),
        ).fetchone()
        if not target:
            return False
        primary = conn.execute(
            """SELECT 1 FROM company_assets
               WHERE company_id = ? AND product_id IS NULL
                 AND json_extract(meta, '$.role') = 'logo'
                 AND COALESCE(json_extract(meta, '$.is_primary'), 0) = 1 LIMIT 1""",
            (company_id,),
        ).fetchone()
        kit = conn.execute("SELECT logo_url FROM brand_kits WHERE company_id = ?", (company_id,)).fetchone()
        if primary or (kit and kit["logo_url"]):
            return False
        conn.execute(
            """UPDATE company_assets
               SET meta = json_set(CASE WHEN json_valid(meta) THEN meta ELSE '{}' END, '$.is_primary', 1)
               WHERE id = ?""",
            (asset_id,),
        )
        now = _now()
        conn.execute("""
            INSERT INTO brand_kits (
                id, company_id, logo_url, colors, extras, source, created_at, updated_at
            ) VALUES (?, ?, ?, '{}', '{}', ?, ?, ?)
            ON CONFLICT(company_id) DO UPDATE SET
                logo_url = excluded.logo_url,
                source = excluded.source,
                updated_at = excluded.updated_at
        """, (_uuid(), company_id, target["url"], brand_source, now, now))
        return True


@_sqlite_retry
def asset_list_photos(company_id: str, product_id: str) -> List[Dict[str, Any]]:
    """Fotos do PRODUTO (role='photo', Fase 2 — base p/ a visão analisar o item real)."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM company_assets
            WHERE company_id = ? AND product_id = ? AND json_extract(meta, '$.role') = 'photo'
            ORDER BY created_at DESC
        """, (company_id, product_id)).fetchall()
        out = []
        for r in rows:
            row = dict(r)
            row["meta"] = json.loads(row.get("meta") or "{}")
            out.append(row)
        return out


# ─────────────────────────────────────────────────────────────────────────────
# Products CRUD
# ─────────────────────────────────────────────────────────────────────────────

@_sqlite_retry
def product_list(company_id: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM products WHERE company_id = ? ORDER BY created_at DESC", (company_id,)).fetchall()
        results = []
        for r in rows:
            row = dict(r)
            row["socials"] = json.loads(row.get("socials") or "{}")
            row["colors"] = json.loads(row.get("colors") or "{}")
            row["functions"] = json.loads(row.get("functions") or "[]")
            row["active"] = bool(row.get("active", 1))
            results.append(row)
        return results


@_sqlite_retry
def product_get(product_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if not row:
            return None
        row = dict(row)
        row["socials"] = json.loads(row.get("socials") or "{}")
        row["colors"] = json.loads(row.get("colors") or "{}")
        row["functions"] = json.loads(row.get("functions") or "[]")
        row["active"] = bool(row.get("active", 1))
        return row


@_sqlite_retry
def product_copy(source_product_id: str, target_company_id: str) -> Optional[Dict[str, Any]]:
    """Duplica um produto de OUTRA empresa pra target_company_id: novo id + slug próprio, mantendo
    nome/descrição/categoria/objetivo/funções/base de conhecimento/cores/web_brief. Cada cópia é
    INDEPENDENTE (editar numa não afeta a origem). NÃO copia logos/fotos (assets do cliente de origem)
    nem soluções — o núcleo que alimenta o briefing (texto/KB) é o que viaja. Retorna o produto ou None."""
    with get_conn() as conn:
        src = conn.execute("SELECT * FROM products WHERE id = ?", (source_product_id,)).fetchone()
    if not src:
        return None
    src = dict(src)
    pid = _uuid()
    now = _now()
    base = _slugify(src.get("name") or "produto")
    slug = base
    with get_conn() as conn:
        n = 1
        while conn.execute("SELECT 1 FROM products WHERE company_id = ? AND slug = ?", (target_company_id, slug)).fetchone():
            slug = f"{base}-{n}"
            n += 1
        conn.execute("""
            INSERT INTO products (id, company_id, name, slug, description, category, website, socials, colors,
                                  active, created_at, updated_at, objective, functions, knowledge, web_brief, web_brief_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
        """, (pid, target_company_id, src.get("name"), slug, src.get("description"), src.get("category"),
              src.get("website"), src.get("socials") or "{}", src.get("colors") or "{}", now, now,
              src.get("objective"), src.get("functions"), src.get("knowledge"),
              src.get("web_brief"), src.get("web_brief_at")))
    return product_get(pid)


@_sqlite_retry
def product_create(company_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    pid = _uuid()
    now = _now()
    slug = _slugify(data.get("name", "produto"))
    with get_conn() as conn:
        base = slug
        n = 1
        while conn.execute("SELECT 1 FROM products WHERE company_id = ? AND slug = ?", (company_id, slug)).fetchone():
            slug = f"{base}-{n}"
            n += 1
    socials = json.dumps(data.get("socials") or {})
    colors = json.dumps(data.get("colors") or {})
    functions = json.dumps(data.get("functions") or [])
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO products (
                id, company_id, name, slug, description, category, website, socials, colors,
                active, created_at, updated_at, objective, functions, knowledge, web_brief, web_brief_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pid, company_id, data.get("name", ""), slug, data.get("description"),
            data.get("category"), data.get("website"), socials, colors, now, now,
            data.get("objective"), functions, data.get("knowledge"), data.get("web_brief"),
            data.get("web_brief_at"),
        ))
    return product_get(pid)


# ── INFLUENCERS (por empresa) — cadastro + banco de imagem (fotos em company_assets) ──
@_sqlite_retry
def cost_log_add(company_id: str, kind: str, model: str, cost_usd: float) -> None:
    """Registra o custo (USD) de UMA geração — pra ver gasto por dia/mês. Silencioso se falhar."""
    try:
        with get_conn() as conn:
            conn.execute("INSERT INTO cost_log (id, company_id, kind, model, cost_usd, created_at) VALUES (?,?,?,?,?,?)",
                         (_uuid(), company_id, kind or "", model or "", float(cost_usd or 0), _now()))
    except Exception:
        pass


def cost_summary(company_id: Optional[str] = None) -> Dict[str, Any]:
    """Soma de custos: hoje, mês, total + nº de gerações. Filtra por empresa se informado."""
    import datetime
    try:
        with get_conn() as conn:
            if company_id:
                rows = conn.execute("SELECT cost_usd, created_at FROM cost_log WHERE company_id=?", (company_id,)).fetchall()
            else:
                rows = conn.execute("SELECT cost_usd, created_at FROM cost_log").fetchall()
    except Exception:
        rows = []
    today = datetime.date.today().isoformat(); month = today[:7]
    t = d = m = 0.0
    for r in rows:
        c = (r[0] or 0); ca = (r[1] or "")
        t += c
        if ca[:10] == today:
            d += c
        if ca[:7] == month:
            m += c
    return {"total_usd": round(t, 4), "today_usd": round(d, 4), "month_usd": round(m, 4), "count": len(rows)}


# ── EMPRESA INFLUENCER (ex.: loucosdatelecom): interna/terceirizada, @ + logo, tem influenciadores embaixo ──
def infcompany_create(company_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    cid = _uuid(); now = _now()
    with get_conn() as conn:
        conn.execute("INSERT INTO influencer_companies (id, company_id, name, handle, kind, website, meta, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (cid, company_id, data.get("name", ""), (data.get("handle") or "").lstrip("@").strip(),
                      (data.get("kind") or "external"), data.get("website"), json.dumps(data.get("meta") or {}), now, now))
    return infcompany_get(cid)


@_sqlite_retry
def infcompany_logos(infcompany_id: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM company_assets WHERE kind='INFCOMPANY_LOGO' AND meta LIKE ? ORDER BY created_at DESC",
                            (f'%"{infcompany_id}"%',)).fetchall()
    out = []
    for r in rows:
        d = dict(r); m = json.loads(d.get("meta") or "{}")
        if m.get("infcompany_id") == infcompany_id:
            d["meta"] = m; out.append(d)
    return out


@_sqlite_retry
def infcompany_get(infcompany_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM influencer_companies WHERE id = ?", (infcompany_id,)).fetchone()
    if not row:
        return None
    d = dict(row); d["meta"] = json.loads(d.get("meta") or "{}")
    d["logos"] = infcompany_logos(infcompany_id); d["influencers"] = influencer_list(infcompany_id=infcompany_id)
    return d


@_sqlite_retry
def infcompany_list(company_id: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM influencer_companies WHERE company_id = ? ORDER BY created_at DESC", (company_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r); d["meta"] = json.loads(d.get("meta") or "{}")
        d["logos"] = infcompany_logos(d["id"]); d["influencers"] = influencer_list(infcompany_id=d["id"])
        out.append(d)
    return out


@_sqlite_retry
def infcompany_update(infcompany_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    fields, vals = [], []
    for k in ("name", "kind", "website"):
        if k in data:
            fields.append(f"{k} = ?"); vals.append(data[k])
    if "handle" in data:
        fields.append("handle = ?"); vals.append((data.get("handle") or "").lstrip("@").strip())
    if "meta" in data:
        fields.append("meta = ?"); vals.append(json.dumps(data.get("meta") or {}))
    if fields:
        fields.append("updated_at = ?"); vals.append(_now()); vals.append(infcompany_id)
        with get_conn() as conn:
            conn.execute(f"UPDATE influencer_companies SET {', '.join(fields)} WHERE id = ?", vals)
    return infcompany_get(infcompany_id)


@_sqlite_retry
def infcompany_delete(infcompany_id: str) -> bool:
    with get_conn() as conn:
        for a in infcompany_logos(infcompany_id):
            conn.execute("DELETE FROM company_assets WHERE id = ?", (a["id"],))
        infs = [r[0] for r in conn.execute("SELECT id FROM influencers WHERE infcompany_id = ?", (infcompany_id,)).fetchall()]
    for i in infs:
        influencer_delete(i)
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM influencer_companies WHERE id = ?", (infcompany_id,))
        return cur.rowcount > 0


def influencer_create(company_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    iid = _uuid(); now = _now()
    with get_conn() as conn:
        conn.execute("INSERT INTO influencers (id, company_id, infcompany_id, name, handle, bio, meta, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (iid, company_id, data.get("infcompany_id"), data.get("name", ""), (data.get("handle") or "").lstrip("@").strip(),
                      data.get("bio"), json.dumps(data.get("meta") or {}), now, now))
    return influencer_get(iid)


@_sqlite_retry
def influencer_photos(influencer_id: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM company_assets WHERE kind='INFLUENCER_PHOTO' AND meta LIKE ? ORDER BY created_at DESC",
                            (f'%"{influencer_id}"%',)).fetchall()
    out = []
    for r in rows:
        d = dict(r); m = json.loads(d.get("meta") or "{}")
        if m.get("influencer_id") == influencer_id:
            d["meta"] = m; out.append(d)
    return out


@_sqlite_retry
def influencer_get(influencer_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM influencers WHERE id = ?", (influencer_id,)).fetchone()
    if not row:
        return None
    d = dict(row); d["meta"] = json.loads(d.get("meta") or "{}"); d["photos"] = influencer_photos(influencer_id)
    return d


@_sqlite_retry
def influencer_list(company_id: Optional[str] = None, infcompany_id: Optional[str] = None) -> List[Dict[str, Any]]:
    if infcompany_id:
        q, arg = "SELECT * FROM influencers WHERE infcompany_id = ?", (infcompany_id,)
    else:
        q, arg = "SELECT * FROM influencers WHERE company_id = ?", (company_id,)
    q += " ORDER BY created_at DESC"
    with get_conn() as conn:
        rows = conn.execute(q, arg).fetchall()
    out = []
    for r in rows:
        d = dict(r); d["meta"] = json.loads(d.get("meta") or "{}"); d["photos"] = influencer_photos(d["id"])
        out.append(d)
    return out


@_sqlite_retry
def influencer_update(influencer_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    fields, vals = [], []
    for k in ("name", "bio", "infcompany_id"):
        if k in data:
            fields.append(f"{k} = ?"); vals.append(data[k])
    if "handle" in data:
        fields.append("handle = ?"); vals.append((data.get("handle") or "").lstrip("@").strip())
    if "meta" in data:
        fields.append("meta = ?"); vals.append(json.dumps(data.get("meta") or {}))
    if fields:
        fields.append("updated_at = ?"); vals.append(_now()); vals.append(influencer_id)
        with get_conn() as conn:
            conn.execute(f"UPDATE influencers SET {', '.join(fields)} WHERE id = ?", vals)
    return influencer_get(influencer_id)


@_sqlite_retry
def influencer_delete(influencer_id: str) -> bool:
    with get_conn() as conn:
        for a in influencer_photos(influencer_id):
            conn.execute("DELETE FROM company_assets WHERE id = ?", (a["id"],))
        cur = conn.execute("DELETE FROM influencers WHERE id = ?", (influencer_id,))
        return cur.rowcount > 0


# ── ORGANIZADOR (empresa do evento, ex.: ExPSP): IG + site + logo; tem vários eventos embaixo ──
def organizer_create(company_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    oid = _uuid(); now = _now()
    with get_conn() as conn:
        conn.execute("INSERT INTO event_organizers (id, company_id, name, instagram, website, meta, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                     (oid, company_id, data.get("name", ""), (data.get("instagram") or "").lstrip("@").strip(),
                      data.get("website"), json.dumps(data.get("meta") or {}), now, now))
    return organizer_get(oid)


@_sqlite_retry
def organizer_logos(organizer_id: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM company_assets WHERE kind='ORGANIZER_LOGO' AND meta LIKE ? ORDER BY created_at DESC",
                            (f'%"{organizer_id}"%',)).fetchall()
    out = []
    for r in rows:
        d = dict(r); m = json.loads(d.get("meta") or "{}")
        if m.get("organizer_id") == organizer_id:
            d["meta"] = m; out.append(d)
    return out


@_sqlite_retry
def organizer_get(organizer_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM event_organizers WHERE id = ?", (organizer_id,)).fetchone()
    if not row:
        return None
    d = dict(row); d["meta"] = json.loads(d.get("meta") or "{}")
    d["logos"] = organizer_logos(organizer_id); d["events"] = event_list(organizer_id=organizer_id)
    return d


@_sqlite_retry
def organizer_list(company_id: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM event_organizers WHERE company_id = ? ORDER BY created_at DESC", (company_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r); d["meta"] = json.loads(d.get("meta") or "{}")
        d["logos"] = organizer_logos(d["id"]); d["events"] = event_list(organizer_id=d["id"])
        out.append(d)
    return out


@_sqlite_retry
def organizer_update(organizer_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    fields, vals = [], []
    for k in ("name", "website"):
        if k in data:
            fields.append(f"{k} = ?"); vals.append(data[k])
    if "instagram" in data:
        fields.append("instagram = ?"); vals.append((data.get("instagram") or "").lstrip("@").strip())
    if "meta" in data:
        fields.append("meta = ?"); vals.append(json.dumps(data.get("meta") or {}))
    if fields:
        fields.append("updated_at = ?"); vals.append(_now()); vals.append(organizer_id)
        with get_conn() as conn:
            conn.execute(f"UPDATE event_organizers SET {', '.join(fields)} WHERE id = ?", vals)
    return organizer_get(organizer_id)


@_sqlite_retry
def organizer_delete(organizer_id: str) -> bool:
    with get_conn() as conn:
        for a in organizer_logos(organizer_id):
            conn.execute("DELETE FROM company_assets WHERE id = ?", (a["id"],))
        evs = [r[0] for r in conn.execute("SELECT id FROM events WHERE organizer_id = ?", (organizer_id,)).fetchall()]
    for e in evs:
        event_delete(e)
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM event_organizers WHERE id = ?", (organizer_id,))
        return cur.rowcount > 0


# ── EVENTO (edição) embaixo do organizador: data início/fim, cidade, descrição, logos + imagens ──
def event_create(company_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    eid = _uuid(); now = _now()
    with get_conn() as conn:
        conn.execute("INSERT INTO events (id, company_id, organizer_id, name, event_date, date_start, date_end, location, description, meta, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (eid, company_id, data.get("organizer_id"), data.get("name", ""),
                      data.get("date_start") or data.get("event_date"), data.get("date_start"), data.get("date_end"),
                      data.get("location"), data.get("description"), json.dumps(data.get("meta") or {}), now, now))
    return event_get(eid)


@_sqlite_retry
def _event_assets(event_id: str, kind: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM company_assets WHERE kind=? AND meta LIKE ? ORDER BY created_at DESC",
                            (kind, f'%"{event_id}"%')).fetchall()
    out = []
    for r in rows:
        d = dict(r); m = json.loads(d.get("meta") or "{}")
        if m.get("event_id") == event_id:
            d["meta"] = m; out.append(d)
    return out


def event_logos(event_id: str) -> List[Dict[str, Any]]:
    return _event_assets(event_id, "EVENT_LOGO")


def event_images(event_id: str) -> List[Dict[str, Any]]:
    return _event_assets(event_id, "EVENT_IMAGE")


@_sqlite_retry
def event_get(event_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if not row:
        return None
    d = dict(row); d["meta"] = json.loads(d.get("meta") or "{}")
    d["logos"] = event_logos(event_id); d["images"] = event_images(event_id)
    return d


@_sqlite_retry
def event_list(company_id: Optional[str] = None, organizer_id: Optional[str] = None) -> List[Dict[str, Any]]:
    if organizer_id:
        q, arg = "SELECT * FROM events WHERE organizer_id = ?", (organizer_id,)
    else:
        q, arg = "SELECT * FROM events WHERE company_id = ?", (company_id,)
    q += " ORDER BY COALESCE(date_start, event_date) DESC, created_at DESC"
    with get_conn() as conn:
        rows = conn.execute(q, arg).fetchall()
    out = []
    for r in rows:
        d = dict(r); d["meta"] = json.loads(d.get("meta") or "{}")
        d["logos"] = event_logos(d["id"]); d["images"] = event_images(d["id"])
        out.append(d)
    return out


@_sqlite_retry
def event_update(event_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    fields, vals = [], []
    for k in ("name", "event_date", "date_start", "date_end", "location", "description", "organizer_id"):
        if k in data:
            fields.append(f"{k} = ?"); vals.append(data[k])
    if "meta" in data:
        fields.append("meta = ?"); vals.append(json.dumps(data.get("meta") or {}))
    if fields:
        fields.append("updated_at = ?"); vals.append(_now()); vals.append(event_id)
        with get_conn() as conn:
            conn.execute(f"UPDATE events SET {', '.join(fields)} WHERE id = ?", vals)
    return event_get(event_id)


@_sqlite_retry
def event_delete(event_id: str) -> bool:
    with get_conn() as conn:
        for a in (event_logos(event_id) + event_images(event_id)):
            conn.execute("DELETE FROM company_assets WHERE id = ?", (a["id"],))
        cur = conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        return cur.rowcount > 0


@_sqlite_retry
def product_update(product_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    now = _now()
    fields = []
    values: List[Any] = []
    for key in ("name", "description", "category", "website", "objective", "knowledge", "web_brief", "web_brief_at"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if "socials" in data:
        fields.append("socials = ?")
        values.append(json.dumps(data["socials"] or {}))
    if "colors" in data:
        fields.append("colors = ?")
        values.append(json.dumps(data["colors"] or {}))
    if "functions" in data:
        fields.append("functions = ?")
        values.append(json.dumps(data["functions"] or []))
    if "active" in data:
        fields.append("active = ?")
        values.append(1 if data["active"] else 0)
    if not fields:
        return product_get(product_id)
    fields.append("updated_at = ?")
    values.append(now)
    values.append(product_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE products SET {', '.join(fields)} WHERE id = ?", values)
    return product_get(product_id)


@_sqlite_retry
def product_delete(product_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
        return cur.rowcount > 0


# ─────────────────────────────────────────────────────────────────────────────
# Solutions (Cliente → Produto → Solução)
# ─────────────────────────────────────────────────────────────────────────────

def _serialize_solution(row: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(row)
    row["links"] = json.loads(row.get("links") or "[]")
    row["active"] = bool(row.get("active", 1))
    return row


@_sqlite_retry
def solution_list(product_id: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM solutions WHERE product_id = ? ORDER BY created_at DESC", (product_id,)).fetchall()
        return [_serialize_solution(r) for r in rows]


@_sqlite_retry
def solution_list_for_company(company_id: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM solutions WHERE company_id = ? ORDER BY created_at DESC", (company_id,)).fetchall()
        return [_serialize_solution(r) for r in rows]


@_sqlite_retry
def solution_get(solution_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM solutions WHERE id = ?", (solution_id,)).fetchone()
        return _serialize_solution(row) if row else None


@_sqlite_retry
def solution_create(product_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    product = product_get(product_id)
    if not product:
        return None
    sid = _uuid()
    now = _now()
    links = json.dumps(data.get("links") or [])
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO solutions (id, company_id, product_id, name, description, links, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        """, (sid, product["company_id"], product_id, data.get("name", ""), data.get("description"), links, now, now))
    return solution_get(sid)


@_sqlite_retry
def solution_update(solution_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    now = _now()
    fields: List[str] = []
    values: List[Any] = []
    for key in ("name", "description"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if "links" in data:
        fields.append("links = ?")
        values.append(json.dumps(data["links"] or []))
    if "active" in data:
        fields.append("active = ?")
        values.append(1 if data["active"] else 0)
    if not fields:
        return solution_get(solution_id)
    fields.append("updated_at = ?")
    values.append(now)
    values.append(solution_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE solutions SET {', '.join(fields)} WHERE id = ?", values)
    return solution_get(solution_id)


@_sqlite_retry
def solution_delete(solution_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM solutions WHERE id = ?", (solution_id,))
        return cur.rowcount > 0


# ─────────────────────────────────────────────────────────────────────────────
# Approval links (public approval page) + notifications log
# ─────────────────────────────────────────────────────────────────────────────

@_sqlite_retry
def approval_link_create(company_id: str, post_ids: List[str], *, stage: str = "client", expires_at: Optional[str] = None) -> Dict[str, Any]:
    token = uuid.uuid4().hex + uuid.uuid4().hex[:8]
    now = _now()
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO approval_links (token, company_id, post_ids, stage, status, created_at, expires_at)
            VALUES (?, ?, ?, ?, 'open', ?, ?)
        """, (token, company_id, json.dumps(post_ids or []), stage, now, expires_at))
    return approval_link_get(token)


@_sqlite_retry
def approval_link_get(token: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM approval_links WHERE token = ?", (token,)).fetchone()
        if not row:
            return None
        row = dict(row)
        row["post_ids"] = json.loads(row.get("post_ids") or "[]")
        return row


@_sqlite_retry
def approval_link_set_status(token: str, status: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE approval_links SET status = ? WHERE token = ?", (status, token))


@_sqlite_retry
def notifications_log_create(data: Dict[str, Any]) -> Dict[str, Any]:
    nid = _uuid()
    now = _now()
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO notifications_log (id, company_id, channel, trigger, recipient, status, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (nid, data.get("company_id"), data.get("channel", ""), data.get("trigger"),
              data.get("recipient"), data.get("status", "sent"), data.get("detail"), now))
    return {"id": nid, **data, "created_at": now}


@_sqlite_retry
def notifications_log_list(company_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        if company_id:
            rows = conn.execute("SELECT * FROM notifications_log WHERE company_id = ? ORDER BY created_at DESC LIMIT ?", (company_id, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM notifications_log ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
