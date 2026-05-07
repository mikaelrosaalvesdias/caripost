import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "runs.db"

# Allow overriding DB location (for container volumes)
_env_db = os.environ.get("ADULT_META_DB_PATH")
if _env_db:
    DB_PATH = Path(_env_db)

try:
    SQLITE_TIMEOUT_SEC = max(5.0, float(os.environ.get("ADULT_META_SQLITE_TIMEOUT_SEC", "30").strip()))
except Exception:
    SQLITE_TIMEOUT_SEC = 30.0
try:
    SQLITE_BUSY_TIMEOUT_MS = max(5000, int(os.environ.get("ADULT_META_SQLITE_BUSY_TIMEOUT_MS", "30000").strip()))
except Exception:
    SQLITE_BUSY_TIMEOUT_MS = 30000
try:
    SQLITE_LOCK_RETRIES = max(0, int(os.environ.get("ADULT_META_SQLITE_LOCK_RETRIES", "3").strip()))
except Exception:
    SQLITE_LOCK_RETRIES = 3
try:
    SQLITE_LOCK_RETRY_SLEEP_SEC = max(0.05, float(os.environ.get("ADULT_META_SQLITE_LOCK_RETRY_SLEEP_SEC", "0.25").strip()))
except Exception:
    SQLITE_LOCK_RETRY_SLEEP_SEC = 0.25


def _is_locked_error(exc: Exception) -> bool:
    msg = str(exc or "").lower()
    return (
        "database is locked" in msg
        or "database table is locked" in msg
        or "database schema is locked" in msg
    )


def _sqlite_retry(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        for attempt in range(SQLITE_LOCK_RETRIES + 1):
            try:
                return fn(*args, **kwargs)
            except sqlite3.OperationalError as exc:
                if not _is_locked_error(exc) or attempt >= SQLITE_LOCK_RETRIES:
                    raise
                time.sleep(SQLITE_LOCK_RETRY_SLEEP_SEC * (attempt + 1))
    return wrapper


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT_SEC)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {int(SQLITE_BUSY_TIMEOUT_MS)}")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@_sqlite_retry
def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
              id TEXT PRIMARY KEY,
              created_at TEXT NOT NULL,
              source TEXT NOT NULL,
              request_json TEXT NOT NULL,
              result_json TEXT NOT NULL,
              error TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at)")

        # Minimal settings storage (internal MVP)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduled_posts (
              id          TEXT PRIMARY KEY,
              run_id      TEXT NOT NULL,
              post_data   TEXT NOT NULL,
              schedule_at TEXT,
              status      TEXT NOT NULL DEFAULT 'pending',
              created_at  TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sched_status ON scheduled_posts(status, schedule_at)"
        )
        # Migration: add sent_at e error_log se ainda não existirem
        _sched_cols = {r[1] for r in conn.execute("PRAGMA table_info(scheduled_posts)").fetchall()}
        if "sent_at" not in _sched_cols:
            conn.execute("ALTER TABLE scheduled_posts ADD COLUMN sent_at TEXT")
        if "error_log" not in _sched_cols:
            conn.execute("ALTER TABLE scheduled_posts ADD COLUMN error_log TEXT")

        # Estado de uploads multipart — persiste através de deploys/reinicializações
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS multipart_uploads (
              upload_id      TEXT PRIMARY KEY,
              object_key     TEXT NOT NULL,
              minio_upload_id TEXT NOT NULL,
              parts_json     TEXT NOT NULL DEFAULT '[]',
              expected_size  INTEGER,
              expected_parts INTEGER,
              created_at     TEXT NOT NULL
            )
            """
        )
        cur = conn.execute("PRAGMA table_info(multipart_uploads)")
        multipart_cols = {str(r[1]) for r in cur.fetchall()}
        if "expected_size" not in multipart_cols:
            conn.execute("ALTER TABLE multipart_uploads ADD COLUMN expected_size INTEGER")
        if "expected_parts" not in multipart_cols:
            conn.execute("ALTER TABLE multipart_uploads ADD COLUMN expected_parts INTEGER")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS multipart_upload_parts (
              upload_id   TEXT NOT NULL,
              part_number INTEGER NOT NULL,
              etag        TEXT NOT NULL,
              created_at  TEXT NOT NULL,
              PRIMARY KEY (upload_id, part_number)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_multipart_parts_upload_id ON multipart_upload_parts(upload_id)"
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS async_jobs (
              kind        TEXT NOT NULL,
              job_id      TEXT NOT NULL,
              status      TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              created_at  TEXT NOT NULL,
              updated_at  TEXT NOT NULL,
              PRIMARY KEY (kind, job_id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_async_jobs_kind_status_created_at ON async_jobs(kind, status, created_at)"
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS upload_metadata (
              object_key   TEXT PRIMARY KEY,
              display_name TEXT NOT NULL DEFAULT '',
              company_id   TEXT NOT NULL DEFAULT '',
              company_name TEXT NOT NULL DEFAULT '',
              created_at   TEXT NOT NULL
            )
            """
        )


@_sqlite_retry
def upload_meta_set(*, object_key: str, display_name: str, company_id: str = "", company_name: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO upload_metadata (object_key, display_name, company_id, company_name, created_at) VALUES (?,?,?,?,?)",
            (object_key, display_name, company_id, company_name, datetime.now(timezone.utc).isoformat()),
        )


@_sqlite_retry
def upload_meta_get(object_key: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM upload_metadata WHERE object_key = ?", (object_key,))
        row = cur.fetchone()
        return dict(row) if row else None


@_sqlite_retry
def upload_meta_get_many(object_keys: List[str]) -> Dict[str, Dict[str, Any]]:
    if not object_keys:
        return {}
    placeholders = ",".join("?" * len(object_keys))
    with get_conn() as conn:
        cur = conn.execute(f"SELECT * FROM upload_metadata WHERE object_key IN ({placeholders})", object_keys)
        return {row["object_key"]: dict(row) for row in cur.fetchall()}


@_sqlite_retry
def insert_run(
    *,
    run_id: str,
    created_at: str,
    source: str,
    request_obj: Dict[str, Any],
    result_obj: Dict[str, Any],
    error: Optional[str] = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO runs (id, created_at, source, request_json, result_json, error) VALUES (?,?,?,?,?,?)",
            (
                run_id,
                created_at,
                source,
                json.dumps(request_obj, ensure_ascii=False),
                json.dumps(result_obj, ensure_ascii=False),
                error,
            ),
        )


@_sqlite_retry
def list_runs(limit: int = 50):
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT id, created_at, source, error,
               json_extract(request_json, '$.original_filename') AS original_filename,
               json_extract(request_json, '$.video_object_key') AS video_object_key
               FROM runs ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


@_sqlite_retry
def get_run(run_id: str) -> Optional[dict]:
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def _replace_media_ref_in_json_value(value: Any, old_ref: str, new_ref: str) -> tuple[Any, bool]:
    changed = False
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, child in value.items():
            next_child, child_changed = _replace_media_ref_in_json_value(child, old_ref, new_ref)
            out[key] = next_child
            changed = changed or child_changed
        return out, changed
    if isinstance(value, list):
        out_list: List[Any] = []
        for child in value:
            next_child, child_changed = _replace_media_ref_in_json_value(child, old_ref, new_ref)
            out_list.append(next_child)
            changed = changed or child_changed
        return out_list, changed
    if not isinstance(value, str):
        return value, False

    if value == old_ref:
        return new_ref, True

    next_value = value
    old_enc = quote(old_ref, safe="")
    new_enc = quote(new_ref, safe="")
    if ("ref=" in next_value or "object_key=" in next_value) and old_enc in next_value:
        next_value = next_value.replace(old_enc, new_enc)
    elif old_ref in next_value and ("local-media" in next_value or "/api/video-" in next_value):
        next_value = next_value.replace(old_ref, new_ref)

    return next_value, next_value != value


@_sqlite_retry
def replace_media_ref_in_runs(*, old_ref: str, new_ref: str) -> int:
    if not old_ref or not new_ref or old_ref == new_ref:
        return 0
    updated = 0
    with get_conn() as conn:
        rows = conn.execute("SELECT id, request_json, result_json FROM runs").fetchall()
        for row in rows:
            run_id = str(row["id"] or "")
            try:
                request_obj = json.loads(row["request_json"]) if isinstance(row["request_json"], str) else (row["request_json"] or {})
            except Exception:
                request_obj = {}
            try:
                result_obj = json.loads(row["result_json"]) if isinstance(row["result_json"], str) else (row["result_json"] or {})
            except Exception:
                result_obj = {}

            next_request, request_changed = _replace_media_ref_in_json_value(request_obj, old_ref, new_ref)
            next_result, result_changed = _replace_media_ref_in_json_value(result_obj, old_ref, new_ref)
            if not request_changed and not result_changed:
                continue

            conn.execute(
                "UPDATE runs SET request_json = ?, result_json = ? WHERE id = ?",
                (
                    json.dumps(next_request, ensure_ascii=False),
                    json.dumps(next_result, ensure_ascii=False),
                    run_id,
                ),
            )
            updated += 1
    return updated


@_sqlite_retry
def update_run_request_field(*, run_id: str, field: str, value: Any) -> bool:
    """Patch a single field inside request_json for an existing run."""
    with get_conn() as conn:
        cur = conn.execute("SELECT request_json FROM runs WHERE id = ?", (run_id,))
        row = cur.fetchone()
        if not row:
            return False
        try:
            req = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
        except Exception:
            req = {}
        req[field] = value
        conn.execute(
            "UPDATE runs SET request_json = ? WHERE id = ?",
            (json.dumps(req, ensure_ascii=False), run_id),
        )
        return True


@_sqlite_retry
def update_run_result_sources(*, run_id: str, sources: Any) -> bool:
    """Atualiza o campo sources dentro de result_json de um run."""
    with get_conn() as conn:
        cur = conn.execute("SELECT result_json FROM runs WHERE id = ?", (run_id,))
        row = cur.fetchone()
        if not row:
            return False
        try:
            result = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
        except Exception:
            result = {}
        result["sources"] = sources
        conn.execute(
            "UPDATE runs SET result_json = ? WHERE id = ?",
            (json.dumps(result, ensure_ascii=False), run_id),
        )
        return True


@_sqlite_retry
def settings_set(*, key: str, value: str, updated_at: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?,?,?)",
            (key, value, updated_at),
        )


@_sqlite_retry
def settings_get(*, key: str) -> Optional[dict]:
    with get_conn() as conn:
        cur = conn.execute("SELECT key, value, updated_at FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return dict(row) if row else None


@_sqlite_retry
def insert_scheduled_post(
    *, id: str, run_id: str, post_data: Dict[str, Any],
    schedule_at: Optional[str], created_at: str,
) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO scheduled_posts (id, run_id, post_data, schedule_at, status, created_at) VALUES (?,?,?,?,?,?)",
            (id, run_id, json.dumps(post_data, ensure_ascii=False), schedule_at, "pending", created_at),
        )


@_sqlite_retry
def list_scheduled_posts(limit: int = 200) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM scheduled_posts ORDER BY schedule_at ASC, created_at DESC LIMIT ?",
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        if isinstance(r.get("post_data"), str):
            try:
                r["post_data"] = json.loads(r["post_data"])
            except Exception:
                pass
    return rows


@_sqlite_retry
def update_scheduled_post_status(*, id: str, status: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("UPDATE scheduled_posts SET status=? WHERE id=?", (status, id))
        return cur.rowcount > 0


@_sqlite_retry
def update_scheduled_post_sent(*, id: str, status: str, sent_at: str, error_log: str = "") -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE scheduled_posts SET status=?, sent_at=?, error_log=? WHERE id=?",
            (status, sent_at, error_log, id),
        )
        return cur.rowcount > 0


@_sqlite_retry
def delete_scheduled_post(*, id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM scheduled_posts WHERE id=?", (id,))
        return cur.rowcount > 0


@_sqlite_retry
def list_scheduled_posts_due(now_iso: str) -> List[Dict[str, Any]]:
    """Retorna posts pending com schedule_at <= now."""
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM scheduled_posts WHERE status='pending' AND schedule_at IS NOT NULL AND schedule_at <= ? ORDER BY schedule_at ASC LIMIT 20",
            (now_iso,),
        )
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        if isinstance(r.get("post_data"), str):
            try:
                r["post_data"] = json.loads(r["post_data"])
            except Exception:
                pass
    return rows


@_sqlite_retry
def multipart_create(
    *,
    upload_id: str,
    object_key: str,
    minio_upload_id: str,
    created_at: str,
    expected_size: Optional[int] = None,
    expected_parts: Optional[int] = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO multipart_uploads
              (upload_id, object_key, minio_upload_id, parts_json, expected_size, expected_parts, created_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (upload_id, object_key, minio_upload_id, "[]", expected_size, expected_parts, created_at),
        )


@_sqlite_retry
def multipart_get(upload_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        cur = conn.execute(
            """
            SELECT upload_id, object_key, minio_upload_id, parts_json, expected_size, expected_parts
            FROM multipart_uploads
            WHERE upload_id = ?
            """,
            (upload_id,),
        )
        row = cur.fetchone()
        part_rows = conn.execute(
            """
            SELECT part_number, etag
            FROM multipart_upload_parts
            WHERE upload_id = ?
            ORDER BY part_number ASC
            """,
            (upload_id,),
        ).fetchall()
    if not row:
        return None
    d = dict(row)
    merged_parts: Dict[int, Dict[str, Any]] = {}
    try:
        legacy_parts = json.loads(d.get("parts_json") or "[]")
    except Exception:
        legacy_parts = []
    if isinstance(legacy_parts, list):
        for p in legacy_parts:
            try:
                pn = int((p or {}).get("PartNumber"))
                etag = str((p or {}).get("ETag") or "").strip()
            except Exception:
                continue
            if pn > 0 and etag:
                merged_parts[pn] = {"PartNumber": pn, "ETag": etag}
    for row_part in part_rows:
        try:
            pn = int(row_part["part_number"])
            etag = str(row_part["etag"] or "").strip()
        except Exception:
            continue
        if pn > 0 and etag:
            merged_parts[pn] = {"PartNumber": pn, "ETag": etag}
    d["parts"] = [merged_parts[pn] for pn in sorted(merged_parts.keys())]
    d.pop("parts_json", None)
    return d


@_sqlite_retry
def multipart_add_part(*, upload_id: str, part_number: int, etag: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO multipart_upload_parts (upload_id, part_number, etag, created_at)
            VALUES (?,?,?,?)
            ON CONFLICT(upload_id, part_number)
            DO UPDATE SET etag = excluded.etag, created_at = excluded.created_at
            """,
            (upload_id, part_number, etag, datetime.now(timezone.utc).isoformat()),
        )


@_sqlite_retry
def multipart_delete(upload_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM multipart_upload_parts WHERE upload_id = ?", (upload_id,))
        conn.execute("DELETE FROM multipart_uploads WHERE upload_id = ?", (upload_id,))


@_sqlite_retry
def multipart_purge_old(*, older_than_hours: int = 48) -> int:
    """Remove uploads abandonados (mais de N horas sem completar)."""
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=older_than_hours)).isoformat()
    with get_conn() as conn:
        stale_rows = conn.execute(
            "SELECT upload_id FROM multipart_uploads WHERE created_at < ?",
            (cutoff_iso,),
        ).fetchall()
        stale_ids = [str(r[0]) for r in stale_rows if r and r[0]]
        if stale_ids:
            conn.executemany(
                "DELETE FROM multipart_upload_parts WHERE upload_id = ?",
                [(upload_id,) for upload_id in stale_ids],
            )
        cur = conn.execute(
            "DELETE FROM multipart_uploads WHERE created_at < ?",
            (cutoff_iso,),
        )
        return cur.rowcount


@_sqlite_retry
def settings_list(prefix: str = ""):
    with get_conn() as conn:
        if prefix:
            cur = conn.execute(
                "SELECT key, updated_at FROM settings WHERE key LIKE ? ORDER BY key ASC",
                (prefix + "%",),
            )
        else:
            cur = conn.execute("SELECT key, updated_at FROM settings ORDER BY key ASC")
        return [dict(r) for r in cur.fetchall()]


def _async_job_decode(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    try:
        payload = json.loads(row["payload_json"]) if isinstance(row["payload_json"], str) else (row["payload_json"] or {})
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload["kind"] = str(payload.get("kind") or row["kind"] or "")
    payload["job_id"] = str(payload.get("job_id") or row["job_id"] or "")
    payload["status"] = str(payload.get("status") or row["status"] or "")
    payload["created_at"] = str(payload.get("created_at") or row["created_at"] or "")
    payload["updated_at"] = str(row["updated_at"] or payload.get("updated_at") or "")
    return payload


@_sqlite_retry
def async_job_get(*, kind: str, job_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT kind, job_id, status, payload_json, created_at, updated_at FROM async_jobs WHERE kind = ? AND job_id = ?",
            (kind, job_id),
        )
        row = cur.fetchone()
    return _async_job_decode(row)


@_sqlite_retry
def async_job_put(
    *,
    kind: str,
    job_id: str,
    payload: Dict[str, Any],
    created_at: Optional[str] = None,
    updated_at: Optional[str] = None,
) -> Dict[str, Any]:
    now_iso = str(updated_at or datetime.now(timezone.utc).isoformat())
    stored = dict(payload or {})
    stored["kind"] = str(stored.get("kind") or kind)
    stored["job_id"] = str(stored.get("job_id") or job_id)
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT created_at FROM async_jobs WHERE kind = ? AND job_id = ?",
            (kind, job_id),
        )
        row = cur.fetchone()
        if created_at:
            created_iso = str(created_at)
        elif row and row[0]:
            created_iso = str(row[0])
        else:
            created_iso = str(stored.get("created_at") or now_iso)
        stored["created_at"] = created_iso
        stored["updated_at"] = now_iso
        status = str(stored.get("status") or "")
        conn.execute(
            """
            INSERT OR REPLACE INTO async_jobs (kind, job_id, status, payload_json, created_at, updated_at)
            VALUES (?,?,?,?,?,?)
            """,
            (
                kind,
                job_id,
                status,
                json.dumps(stored, ensure_ascii=False),
                created_iso,
                now_iso,
            ),
        )
    return stored


def async_job_merge(
    *,
    kind: str,
    job_id: str,
    patch: Dict[str, Any],
    created_at: Optional[str] = None,
    updated_at: Optional[str] = None,
) -> Dict[str, Any]:
    current = async_job_get(kind=kind, job_id=job_id) or {}
    merged = dict(current)
    merged.update(dict(patch or {}))
    return async_job_put(
        kind=kind,
        job_id=job_id,
        payload=merged,
        created_at=created_at or current.get("created_at"),
        updated_at=updated_at,
    )


@_sqlite_retry
def async_job_list(*, kind: str, statuses: Optional[List[str]] = None, limit: int = 200) -> List[Dict[str, Any]]:
    sql = (
        "SELECT kind, job_id, status, payload_json, created_at, updated_at "
        "FROM async_jobs WHERE kind = ?"
    )
    params: List[Any] = [kind]
    if statuses:
        safe_statuses = [str(s) for s in statuses if str(s).strip()]
        if safe_statuses:
            placeholders = ",".join("?" for _ in safe_statuses)
            sql += f" AND status IN ({placeholders})"
            params.extend(safe_statuses)
    sql += " ORDER BY created_at ASC LIMIT ?"
    params.append(max(1, int(limit or 200)))
    with get_conn() as conn:
        cur = conn.execute(sql, tuple(params))
        rows = cur.fetchall()
    items: List[Dict[str, Any]] = []
    for row in rows:
        decoded = _async_job_decode(row)
        if decoded is not None:
            items.append(decoded)
    return items


@_sqlite_retry
def async_jobs_fail_incomplete(*, kinds: Optional[List[str]] = None, error: str, detail: str) -> int:
    safe_kinds = [str(k) for k in (kinds or []) if str(k).strip()]
    now_iso = datetime.now(timezone.utc).isoformat()
    sql = (
        "SELECT kind, job_id, status, payload_json, created_at, updated_at "
        "FROM async_jobs WHERE status IN ('pending', 'running')"
    )
    params: List[Any] = []
    if safe_kinds:
        placeholders = ",".join("?" for _ in safe_kinds)
        sql += f" AND kind IN ({placeholders})"
        params.extend(safe_kinds)
    with get_conn() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
        updated = 0
        for row in rows:
            payload = _async_job_decode(row) or {}
            payload["status"] = "error"
            payload["error"] = str(error or "interrupted")
            payload["detail"] = str(detail or "Processamento interrompido.")
            payload["updated_at"] = now_iso
            conn.execute(
                """
                UPDATE async_jobs
                   SET status = ?, payload_json = ?, updated_at = ?
                 WHERE kind = ? AND job_id = ?
                """,
                (
                    payload["status"],
                    json.dumps(payload, ensure_ascii=False),
                    now_iso,
                    row["kind"],
                    row["job_id"],
                ),
            )
            updated += 1
    return updated


