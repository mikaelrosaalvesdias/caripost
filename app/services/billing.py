"""
Billing por EMPRESA (Marco 4 — venda de acesso): medição de gasto + saldo de créditos + feature flags.

Modelo:
  - 1 crédito da plataforma = US$ do setting `billing.credit_usd` (default 0.01 → 1 crédito ≈ 1 centavo de dólar).
    Você vende créditos no preço que quiser; o custo real de IA é convertido e DEBITADO do saldo da empresa.
  - `usage_log` grava TODO gasto (kind image/video/text/enrich, provider, modelo, custo USD, créditos) por empresa.
  - Enforcement é OPT-IN: setting `billing.enforce` ligado → empresa sem saldo recebe 402 e não gera.
    Desligado (default) → só mede (não quebra o uso atual do dono).
  - Feature flags por empresa: coluna `companies.features` (JSON) — ex.: {"video": false, "estudio": true}.
    `feature_enabled()` default True (tudo liberado até você bloquear).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..db import get_conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _credit_usd() -> float:
    try:
        from .ai import get_setting
        return max(0.0001, float(get_setting("billing.credit_usd") or 0.01))
    except Exception:
        return 0.01


def enforce_on() -> bool:
    try:
        from .ai import get_setting
        return (get_setting("billing.enforce") or "").strip().lower() in ("1", "true", "on", "yes")
    except Exception:
        return False


def get_balance(company_id: str) -> float:
    with get_conn() as c:
        row = c.execute("SELECT balance FROM company_credits WHERE company_id=?", (company_id,)).fetchone()
        return float(row[0]) if row else 0.0


def add_credits(company_id: str, amount: float) -> float:
    """Recarga (ou ajuste negativo) manual pelo admin. Retorna o novo saldo."""
    with get_conn() as c:
        c.execute("INSERT INTO company_credits(company_id, balance, updated_at) VALUES (?, ?, ?) "
                  "ON CONFLICT(company_id) DO UPDATE SET balance = balance + ?, updated_at = ?",
                  (company_id, float(amount), _now(), float(amount), _now()))
    return get_balance(company_id)


def log_usage(company_id: str, kind: str, cost_usd: float = 0.0, provider: str = "",
              model: str = "", meta: Optional[Dict[str, Any]] = None) -> float:
    """Grava o gasto e DEBITA os créditos equivalentes do saldo da empresa. Retorna créditos debitados."""
    credits = round(float(cost_usd or 0.0) / _credit_usd(), 4)
    try:
        with get_conn() as c:
            c.execute("INSERT INTO usage_log(company_id, kind, provider, model, cost_usd, credits, meta, created_at) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (company_id, kind, provider, model, float(cost_usd or 0.0), credits,
                       json.dumps(meta or {}), _now()))
            if credits:
                c.execute("INSERT INTO company_credits(company_id, balance, updated_at) VALUES (?, ?, ?) "
                          "ON CONFLICT(company_id) DO UPDATE SET balance = balance - ?, updated_at = ?",
                          (company_id, -credits, _now(), credits, _now()))
    except Exception:
        pass
    return credits


def check_credits(company_id: str) -> Optional[str]:
    """None = pode gerar. String = motivo do bloqueio (só quando billing.enforce ligado)."""
    if not enforce_on():
        return None
    bal = get_balance(company_id)
    if bal <= 0:
        return f"Sem créditos (saldo {bal:.1f}). Recarregue para continuar gerando."
    return None


def feature_enabled(company: Dict[str, Any], key: str) -> bool:
    """Flag por empresa (companies.features JSON). Ausente = LIBERADO (bloqueio é opt-in do admin)."""
    try:
        f = company.get("features")
        if isinstance(f, str):
            f = json.loads(f or "{}")
        return bool((f or {}).get(key, True))
    except Exception:
        return True


def get_features(company_id: str) -> Dict[str, Any]:
    """Feature flags da empresa (dict). Ausente = tudo liberado (bloqueio é opt-in do admin)."""
    try:
        with get_conn() as c:
            row = c.execute("SELECT features FROM companies WHERE id=?", (company_id,)).fetchone()
        return json.loads(row[0]) if row and row[0] else {}
    except Exception:
        return {}


def set_features(company_id: str, features: Dict[str, Any]) -> None:
    with get_conn() as c:
        c.execute("UPDATE companies SET features=?, updated_at=? WHERE id=?",
                  (json.dumps(features or {}), _now(), company_id))


def usage_summary(company_id: Optional[str] = None, days: int = 30) -> List[Dict[str, Any]]:
    """Resumo de gasto por empresa (e por tipo) nos últimos N dias + saldo atual."""
    with get_conn() as c:
        where, args = "", []
        if company_id:
            where, args = "AND u.company_id=?", [company_id]
        rows = c.execute(
            f"SELECT u.company_id, u.kind, COUNT(*) n, SUM(u.cost_usd) usd, SUM(u.credits) creds "
            f"FROM usage_log u WHERE u.created_at >= datetime('now', ?) {where} "
            f"GROUP BY u.company_id, u.kind ORDER BY u.company_id, usd DESC",
            [f"-{int(days)} days"] + args).fetchall()
        out: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            cid = r[0]
            e = out.setdefault(cid, {"company_id": cid, "balance": get_balance(cid), "kinds": [], "total_usd": 0.0, "total_credits": 0.0})
            e["kinds"].append({"kind": r[1], "count": r[2], "cost_usd": round(r[3] or 0, 4), "credits": round(r[4] or 0, 2)})
            e["total_usd"] += (r[3] or 0)
            e["total_credits"] += (r[4] or 0)
        for e in out.values():
            e["total_usd"] = round(e["total_usd"], 4)
            e["total_credits"] = round(e["total_credits"], 2)
        return list(out.values())
