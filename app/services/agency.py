"""Agência automática: calendário editorial mensal por empresa.

Etapa 1 (este módulo): monta os SLOTS do mês (datas/horários/formatos, em Python — determinístico) e a IA
preenche cada slot com IDEIA + LEGENDA pronta. O dono aprova/reprova ideia por ideia. A produção das artes
(etapa 2) reusa o pipeline aprovado (generate_carousel + render-carousel).

Tudo configurável por empresa em brand_kit.creative_config.agency (mix, pilares, horário, dias, CTA, estilo).
"""
from __future__ import annotations

import asyncio
import calendar
import json
import logging
import os
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ..db import get_conn, _sqlite_retry

log = logging.getLogger("agency")

AGENCY_DEFAULTS: Dict[str, Any] = {
    "enabled": False,
    "mix": {"post": 14, "carrossel": 6, "reels": 2},
    "time": "18:00",
    "weekdays": [0, 1, 2, 3, 4, 5],          # seg–sáb (0 = segunda)
    "batch": 6,                               # peças por chamada de IA (fica abaixo do timeout do provedor)
    "pillars": [
        {"name": "Educação e mercado", "weight": 35,
         "desc": "Conteúdo que ensina o público-alvo: tendências do setor dele, regulação, tributação, gestão, "
                 "como crescer e reter clientes. Autoridade sem cara de venda, fechando com CTA leve."},
        {"name": "Produto em destaque", "weight": 35,
         "desc": "Um produto/app do catálogo por peça: o benefício concreto PARA O PÚBLICO-ALVO (não para o consumidor "
                 "final, se a empresa for B2B). Use fatos reais do catálogo."},
        {"name": "Datas e eventos", "weight": 15,
         "desc": "Datas comemorativas do mês ligadas a um produto, e eventos do setor cadastrados."},
        {"name": "Autoridade e relacionamento", "weight": 15,
         "desc": "Bastidores, visitas e parcerias, planejamento, pesquisa de mercado, dicas práticas, números do setor."},
    ],
    "cta": "",            # vazio → "Fale com a {empresa} (link na bio)"
    "whatsapp": "",
    "hashtags_base": [],
    "style": (
        "Estrutura de legenda que funciona: 1ª linha = gancho forte (pergunta ou afirmação provocativa). "
        "2–4 parágrafos curtos de valor (pode usar lista com •). Feche com CTA claro (ex.: 'Fale com a gente e "
        "descubra como (link na bio)'). Depois 5–8 hashtags (marca + setor + tema). Tom consultivo, direto, "
        "português do Brasil com acentuação correta, sem exagero de emoji. Título da arte curto (até ~9 palavras), "
        "impactante, diferente da 1ª linha da legenda."
    ),
}

FORMAT_LABEL = {"post": "post fixo (1 arte)", "carrossel": "carrossel (5–8 telas)", "reels": "reels (vídeo curto ~30s)"}
WEEKDAY_PT = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
_JOBS: Dict[str, asyncio.Task] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def agency_cfg(company: Dict[str, Any]) -> Dict[str, Any]:
    ov = (((company or {}).get("brand_kit") or {}).get("creative_config") or {}).get("agency") or {}
    out = json.loads(json.dumps(AGENCY_DEFAULTS))
    if isinstance(ov, dict):
        for k, v in ov.items():
            if v not in (None, "", [], {}):
                out[k] = v
    return out


# ─────────────────────────────── datas comemorativas ───────────────────────────────

def _easter(y: int) -> date:
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(y, month, day)


def _nth_weekday(y: int, m: int, weekday: int, n: int) -> date:
    d = date(y, m, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def month_dates(year: int, month: int, company: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Datas comemorativas do mês (fixas + móveis) + eventos cadastrados da empresa."""
    path = os.path.join(os.path.dirname(__file__), "datas_comemorativas.json")
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception:
        data = {"fixas": [], "moveis": []}
    out: List[Dict[str, Any]] = []
    for d in data.get("fixas", []):
        mm, dd = d["md"].split("-")
        if int(mm) == month:
            out.append({"date": date(year, month, int(dd)).isoformat(), "nome": d["nome"], "apps": d.get("apps", [])})
    rules = {
        "carnaval": lambda: _easter(year) - timedelta(days=47),
        "internet_segura": lambda: _nth_weekday(year, 2, 1, 2),
        "maes": lambda: _nth_weekday(year, 5, 6, 2),
        "pais": lambda: _nth_weekday(year, 8, 6, 2),
        "black_friday": lambda: _nth_weekday(year, 11, 3, 4) + timedelta(days=1),
    }
    for d in data.get("moveis", []):
        fn = rules.get(d.get("regra"))
        if fn:
            dt = fn()
            if dt.month == month:
                out.append({"date": dt.isoformat(), "nome": d["nome"], "apps": d.get("apps", [])})
    if company:
        try:
            from ..db_companies import event_list
            for ev in event_list(company["id"]) or []:
                ds = (ev.get("date_start") or ev.get("event_date") or "")[:10]
                if ds[:7] == f"{year:04d}-{month:02d}":
                    out.append({"date": ds, "nome": "Evento: " + (ev.get("name") or ""), "apps": [],
                                "evento": (ev.get("description") or "")[:300], "local": ev.get("location") or ""})
        except Exception:
            pass
    return sorted(out, key=lambda x: x["date"])


# ─────────────────────────────── slots (determinístico) ───────────────────────────────

def build_slots(year: int, month: int, cfg: Dict[str, Any], dates: List[Dict[str, Any]],
                today: Optional[date] = None) -> List[Dict[str, Any]]:
    mix = {k: int(v or 0) for k, v in (cfg.get("mix") or {}).items() if k in FORMAT_LABEL}
    total = sum(mix.values())
    if total <= 0:
        return []
    today = today or datetime.now().date()
    wd = set(int(x) for x in (cfg.get("weekdays") or [0, 1, 2, 3, 4, 5]))
    ndays = calendar.monthrange(year, month)[1]
    days = [date(year, month, d) for d in range(1, ndays + 1)]
    days = [d for d in days if d.weekday() in wd and d > today] or [d for d in days if d > today]
    if not days:
        return []
    # espalha uniformemente; se faltar dia, repete dias (2 peças no mesmo dia, horários diferentes)
    picked = [days[min(len(days) - 1, int(i * len(days) / total))] for i in range(total)]
    # garante as datas comemorativas/eventos (troca o dia mais próximo ainda não "temático")
    themed = set()
    for dd in dates:
        d = date.fromisoformat(dd["date"])
        if d <= today or d in picked:
            themed.add(d)
            continue
        free = [i for i, p in enumerate(picked) if p not in themed]
        if not free:
            break
        j = min(free, key=lambda i: abs((picked[i] - d).days))
        picked[j] = d
        themed.add(d)
    picked.sort()
    # formatos: carrosséis e reels espalhados, o resto post
    fmts = ["post"] * total
    pos = 0
    for f in ("carrossel", "reels"):
        n = mix.get(f, 0)
        for i in range(n):
            idx = int((i + 0.5) * total / max(1, n)) % total
            while fmts[idx] != "post":
                idx = (idx + 1) % total
            fmts[idx] = f
            pos += 1
    hh, mm = (cfg.get("time") or "18:00").split(":")[:2]
    seen: Dict[date, int] = {}
    out = []
    by_date = {}
    for dd in dates:
        by_date.setdefault(dd["date"], []).append(dd)
    for i, (d, f) in enumerate(zip(picked, fmts)):
        k = seen.get(d, 0)
        seen[d] = k + 1
        h = int(hh) - 6 * k if k else int(hh)      # 2ª peça no mesmo dia vai ao meio-dia
        out.append({"i": i, "date": d.isoformat(), "weekday": WEEKDAY_PT[d.weekday()], "time": f"{h:02d}:{mm}",
                    "format": f, "datas": [x["nome"] for x in by_date.get(d.isoformat(), [])]})
    return out


# ─────────────────────────────── DB ───────────────────────────────

def _row(r) -> Dict[str, Any]:
    d = dict(r)
    for k in ("config", "meta"):
        if k in d:
            try:
                d[k] = json.loads(d[k] or "{}")
            except Exception:
                d[k] = {}
    return d


@_sqlite_retry
def plan_create(company_id: str, month: str, config: Dict[str, Any]) -> Dict[str, Any]:
    pid, now = uuid.uuid4().hex, _now()
    with get_conn() as conn:
        conn.execute("INSERT INTO editorial_plans (id, company_id, month, status, config, created_at, updated_at) "
                     "VALUES (?, ?, ?, 'generating', ?, ?, ?)", (pid, company_id, month, json.dumps(config), now, now))
    return plan_get(pid)


def plan_get(plan_id: str, with_items: bool = True) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM editorial_plans WHERE id = ?", (plan_id,)).fetchone()
        if not r:
            return None
        p = _row(r)
        if with_items:
            p["items"] = [_row(x) for x in conn.execute(
                "SELECT * FROM editorial_items WHERE plan_id = ? ORDER BY slot_at, created_at", (plan_id,)).fetchall()]
    return p


def plan_list(company_id: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT p.*, (SELECT COUNT(*) FROM editorial_items i WHERE i.plan_id = p.id) AS n_items, "
                            "(SELECT COUNT(*) FROM editorial_items i WHERE i.plan_id = p.id AND i.stage != 'idea' "
                            " AND i.stage != 'idea_rejected') AS n_ok FROM editorial_plans p WHERE p.company_id = ? "
                            "ORDER BY p.month DESC, p.created_at DESC", (company_id,)).fetchall()
    return [_row(r) for r in rows]


@_sqlite_retry
def plan_update(plan_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = _now()
    with get_conn() as conn:
        conn.execute(f"UPDATE editorial_plans SET {', '.join(k + ' = ?' for k in fields)} WHERE id = ?",
                     [*fields.values(), plan_id])


@_sqlite_retry
def plan_delete(plan_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM editorial_items WHERE plan_id = ?", (plan_id,))
        conn.execute("DELETE FROM editorial_plans WHERE id = ?", (plan_id,))


ITEM_FIELDS = ("slot_at", "format", "pillar", "product", "date_hint", "title", "angle", "copy", "hashtags",
               "art_brief", "stage", "review_comment", "post_id", "social_post_id", "error")


@_sqlite_retry
def item_insert(plan_id: str, company_id: str, data: Dict[str, Any]) -> str:
    iid, now = uuid.uuid4().hex, _now()
    cols = [k for k in ITEM_FIELDS if k in data]
    with get_conn() as conn:
        conn.execute(f"INSERT INTO editorial_items (id, plan_id, company_id, {', '.join(cols)}, meta, created_at, updated_at) "
                     f"VALUES (?, ?, ?, {', '.join('?' for _ in cols)}, ?, ?, ?)",
                     [iid, plan_id, company_id, *[data[k] for k in cols], json.dumps(data.get("meta") or {}), now, now])
    return iid


def item_get(item_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM editorial_items WHERE id = ?", (item_id,)).fetchone()
    return _row(r) if r else None


@_sqlite_retry
def item_update(item_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sets = {k: data[k] for k in ITEM_FIELDS if k in data}
    if "meta" in data:
        sets["meta"] = json.dumps(data["meta"] or {})
    if sets:
        sets["updated_at"] = _now()
        with get_conn() as conn:
            conn.execute(f"UPDATE editorial_items SET {', '.join(k + ' = ?' for k in sets)} WHERE id = ?",
                         [*sets.values(), item_id])
    return item_get(item_id)


def recent_titles(company_id: str, exclude_plan: str = "", limit: int = 60) -> List[str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT title FROM editorial_items WHERE company_id = ? AND plan_id != ? AND title IS NOT NULL "
                            "AND stage != 'idea_rejected' ORDER BY slot_at DESC LIMIT ?", (company_id, exclude_plan, limit)).fetchall()
    return [r[0] for r in rows if r[0]]


# ─────────────────────────────── IA ───────────────────────────────

def _catalog_context(company: Dict[str, Any]) -> str:
    from ..db_companies import product_list, product_plan_list, solution_list
    lines = []
    for p in product_list(company["id"]) or []:
        if p.get("active") is False:
            continue
        plans = [x.get("name") for x in (product_plan_list(p["id"]) or []) if x.get("name")]
        sols = [x.get("name") for x in (solution_list(p["id"]) or []) if x.get("name")]
        desc = (p.get("description") or p.get("objective") or "").strip().replace("\n", " ")[:260]
        facts = " ".join((p.get("knowledge") or "").split())[:450]
        lines.append(f"- {p['name']} ({p.get('category') or ''}): {desc}" + (f" | fatos: {facts}" if facts else "")
                     + (f" | planos: {', '.join(plans)}" if plans else "")
                     + (f" | adicionais: {', '.join(sols)}" if sols else ""))
    return "\n".join(lines) or "(catálogo vazio — fale da empresa e do setor)"


def _system(company: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    return ("Você é o estrategista e redator-chefe de uma agência de social media que cuida do Instagram da empresa "
            f"{company.get('name')}. Planeja o calendário editorial do mês e escreve legendas prontas para publicar. "
            "Responda SOMENTE com JSON válido, sem comentários.")


def _brief_block(company: Dict[str, Any], cfg: Dict[str, Any], dates: List[Dict[str, Any]]) -> str:
    bk = company.get("brand_kit") or {}
    socials = company.get("socials") or {}
    cta = cfg.get("cta") or f"Fale com a {company.get('name')} (link na bio)"
    pillars = "\n".join(f"- {p['name']} (~{p.get('weight', 0)}%): {p.get('desc', '')}" for p in cfg.get("pillars") or [])
    dts = "\n".join(f"- {d['date']}: {d['nome']}" + (f" (ganchos: {', '.join(d['apps'])})" if d.get("apps") else "")
                    + (f" — {d.get('evento')}" if d.get("evento") else "") for d in dates) or "- (nenhuma)"
    return (
        f"EMPRESA: {company.get('name')} — {company.get('segment') or ''}. Site: {company.get('website') or ''}. "
        f"Instagram: {socials.get('instagram') or ''}.\n"
        f"PÚBLICO (fale COM ele, à risca): {(bk.get('audience') or 'público-alvo da marca').strip()}\n"
        f"VOZ: {(bk.get('voice') or '').strip()[:400]}\n"
        f"CATÁLOGO (use SÓ estes produtos, nomes exatos; fatos reais):\n{_catalog_context(company)}\n"
        f"PILARES E PESOS:\n{pillars}\n"
        f"DATAS DO MÊS:\n{dts}\n"
        f"CTA PADRÃO: {cta}" + (f" | WhatsApp comercial: {cfg['whatsapp']}" if cfg.get("whatsapp") else "") + "\n"
        f"HASHTAGS-BASE (inclua as relevantes): {' '.join(cfg.get('hashtags_base') or [])}\n"
        f"ESTILO: {cfg.get('style')}\n"
    )


_SCHEMA = ('{"items":[{"i":<índice do slot>,"pillar":"<nome do pilar>","product":"<nome exato do catálogo ou vazio se institucional>",'
           '"title":"<título curto da arte>","angle":"<o que a peça ensina/defende, 1-2 frases>",'
           '"copy":"<legenda completa pronta, com \\n entre parágrafos, gancho na 1ª linha e CTA no fim>",'
           '"hashtags":"#a #b ...","art_brief":"<direção de arte: cena/visual e, se carrossel, a sequência de telas; '
           'se reels, roteiro em cenas com falas>"}]}')


def _ai_fill(company: Dict[str, Any], cfg: Dict[str, Any], dates: List[Dict[str, Any]], slots: List[Dict[str, Any]],
             avoid: List[str], extra: str = "") -> List[Dict[str, Any]]:
    from .ai import cheap_text_config, complete_ai, extract_json, get_ai_config
    main = get_ai_config()
    # Cadeia de provedores: rápido (assinatura) → principal (assinatura) → CometAPI (pago, só se os outros falharem).
    cheap = cheap_text_config(main)
    configs = [cheap, main]
    if (main or {}).get("provider") == "omniroute":
        # gateway das assinaturas: tenta outros modelos antes de cair no pago (configurável em agency.models)
        # padrão: GPT-5.5 (assinatura Codex) → Sonnet (assinatura) → Opus (assinatura) → kie (PAGO em créditos, último)
        models = cfg.get("models") or ["cx/gpt-5.6-sol", main.get("model"), "cx/gpt-5.6-luna", (cheap or {}).get("model"), "kie/claude-sonnet-4-6"]
        configs = [dict(main, model=m) for m in dict.fromkeys(m for m in models if m)]
    configs = [c for c in configs if c]
    if not configs:
        raise ValueError("IA de texto não configurada.")
    slot_days = {s["date"] for s in slots}
    user = (_brief_block(company, cfg, [d for d in dates if d["date"] in slot_days])   # só as datas DESTES slots
            + "\nSLOTS A PREENCHER (respeite formato e data; se o slot tem data comemorativa/evento, a peça é sobre ela):\n"
            + "\n".join(f"- i={s['i']} | {s['date']} ({s['weekday']}) {s['time']} | {FORMAT_LABEL[s['format']]}"
                        + (f" | DATA: {', '.join(s['datas'])}" if s.get("datas") else "") for s in slots)
            + ("\n\nNÃO REPITA estes temas/títulos já usados:\n- " + "\n- ".join(avoid[:80]) if avoid else "")
            + (f"\n\n{extra}" if extra else "")
            + "\n\nRegras:\n"
              "- DATAS COMEMORATIVAS/EVENTOS: só nas peças cujo slot traz 'DATA:'. Nos demais slots NÃO fale de datas do mês "
              "(elas já têm peça própria). Data sem relação com o público/negócio: faça uma peça normal do pilar, sem forçar.\n"
              "- PRODUTOS: varie; prefira os menos usados no mês; no máximo 2 peças por produto no mês inteiro; nunca o mesmo "
              "produto em peças seguidas; reels e carrosséis também variam de produto.\n"
              "- Varie pilares conforme os pesos; cada peça com ângulo diferente; nada de preço/condição fora do catálogo.\n"
              "- ORIGINALIDADE: os exemplos de estilo são referência de TOM; NUNCA copie títulos ou frases deles.\n"
              "- Títulos em caixa de frase (só a 1ª letra maiúscula, exceto nomes próprios). Títulos CONCRETOS e com tensão "
              "(pergunta incômoda, contraste, número, erro comum, benefício mensurável). Proibido título vago como "
              "'Dicas práticas para…', 'Bastidores da inovação', 'Entenda sua importância', 'X que transforma'.\n"
              "- Use FATOS reais do catálogo (recursos, números, planos) nas legendas; nada genérico que serviria a qualquer empresa.\n"
              "- art_brief de CARROSSEL: liste as telas ('Tela 1 (capa): ...; Tela 2: ...; ...; Última: CTA'). "
              "art_brief de REELS (obrigatório neste formato): 'Cena 1 (0–5s): visual … | fala: …' e assim até 5 cenas (~30s), "
              "com gancho nos 3 primeiros segundos e CTA na última cena. "
              "art_brief de POST: a cena/visual da arte e o texto curto que vai nela.\n"
            + "Formato da resposta: " + _SCHEMA)
    raw, last = "", None
    for config in configs:
        try:
            raw = complete_ai(config, _system(company, cfg), user, 8000)
            break
        except Exception as exc:
            log.warning("agency IA %s/%s falhou: %s", config.get("provider"), config.get("model"), str(exc)[:120])
            last = exc
    if not raw and last:
        raise last
    data = extract_json(raw) or {}
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("IA não devolveu o calendário em JSON.")
    return items


def _norm_item(it: Dict[str, Any], slot: Dict[str, Any], product_names: List[str]) -> Dict[str, Any]:
    prod = (it.get("product") or "").strip()
    match = next((n for n in product_names if n.lower() == prod.lower()), "")
    return {
        "slot_at": f"{slot['date']}T{slot['time']}:00", "format": slot["format"],
        "pillar": (it.get("pillar") or "").strip()[:80], "product": match,
        "date_hint": ", ".join(slot.get("datas") or []),
        "title": (it.get("title") or "").strip()[:160], "angle": (it.get("angle") or "").strip()[:600],
        "copy": (it.get("copy") or "").strip()[:2200], "hashtags": (it.get("hashtags") or "").strip()[:400],
        "art_brief": (it.get("art_brief") or "").strip()[:2000], "stage": "idea",
    }


def _generate_plan_sync(plan_id: str) -> None:
    from ..db_companies import company_get, product_list
    plan = plan_get(plan_id, with_items=False)
    company = company_get(plan["company_id"])
    cfg = plan["config"] or agency_cfg(company)
    _ov = ((company.get("brand_kit") or {}).get("creative_config") or {}).get("agency") or {}
    if not (_ov.get("pillars") and _ov.get("style")):
        # 1º calendário do cliente: IA monta a linha editorial SOB MEDIDA a partir do cadastro e salva.
        plan_update(plan_id, error="montando a linha editorial deste cliente")
        try:
            tailored = ensure_tailored_config(company["id"])
            for k in ("pillars", "style", "cta", "hashtags_base", "whatsapp"):
                if tailored.get(k):
                    cfg[k] = tailored[k]
            plan_update(plan_id, config=json.dumps(cfg))
            company = company_get(plan["company_id"])
        except Exception as exc:
            log.warning("agency: linha editorial sob medida falhou (%s) — seguindo com a padrão", exc)
    y, m = map(int, plan["month"].split("-"))
    dates = month_dates(y, m, company)
    slots = build_slots(y, m, cfg, dates)
    if not slots:
        raise ValueError("Não há dias disponíveis neste mês (já passou?).")
    names = [p["name"] for p in product_list(company["id"]) or []]
    avoid = recent_titles(company["id"], exclude_plan=plan_id)
    bs = max(3, int(cfg.get("batch") or 6))
    done = 0
    used: Dict[str, int] = {n: 0 for n in names}
    for k in range(0, len(slots), bs):
        chunk = slots[k:k + bs]
        items = []
        usage = ("USO DE PRODUTOS ATÉ AGORA NO MÊS (prefira os de menor número; 2 = esgotado): "
                 + ", ".join(f"{n} ({c})" for n, c in sorted(used.items(), key=lambda x: x[1])))
        for attempt in range(5):
            try:
                items = _ai_fill(company, cfg, dates, chunk, avoid, usage)
                break
            except Exception as exc:
                log.warning("agency plan %s lote %s tentativa %s: %s", plan_id, k, attempt + 1, exc)
                if attempt == 4:
                    items = []      # lote perdido: as peças entram vazias com "Refazer" (não derruba o mês inteiro)
                    break
                plan_update(plan_id, error=f"gerando {done}/{len(slots)} (provedor de IA ocupado, tentando de novo)")
                time.sleep(30 * (attempt + 1))      # 429/instabilidade do provedor: espera progressiva (~5 min no total)
        by_i = {int(x.get("i", -1)): x for x in items if isinstance(x, dict) and str(x.get("i", "")).lstrip("-").isdigit()}
        for n, s in enumerate(chunk):
            it = by_i.get(s["i"]) or (items[n] if n < len(items) and isinstance(items[n], dict) else {})
            row = _norm_item(it, s, names)
            if not row["title"]:
                row.update(stage="idea", error="A IA não preencheu esta ideia — clique em Refazer.")
            item_insert(plan_id, company["id"], row)
            if row["title"]:
                avoid.insert(0, row["title"])
            if row["product"]:
                used[row["product"]] = used.get(row["product"], 0) + 1
            done += 1
        plan_update(plan_id, error=f"gerando {done}/{len(slots)}")
    empty = sum(1 for i in (plan_get(plan_id) or {}).get("items", []) if not i.get("title"))
    plan_update(plan_id, status="ideas",
                error=(f"{empty} peça(s) ficaram sem ideia (provedor de IA ocupado) — use Refazer nelas." if empty else None))


def start_plan_generation(plan_id: str) -> None:
    async def _run():
        try:
            await asyncio.to_thread(_generate_plan_sync, plan_id)
        except Exception as exc:
            log.exception("agency plan %s falhou", plan_id)
            plan_update(plan_id, status="error", error=str(exc)[:500])
        finally:
            _JOBS.pop(plan_id, None)
    _JOBS[plan_id] = asyncio.create_task(_run())


def regenerate_item_sync(item_id: str, comment: str = "") -> Dict[str, Any]:
    from ..db_companies import company_get, product_list
    item = item_get(item_id)
    plan = plan_get(item["plan_id"], with_items=True)
    company = company_get(item["company_id"])
    cfg = plan["config"] or agency_cfg(company)
    y, m = map(int, plan["month"].split("-"))
    dates = month_dates(y, m, company)
    d = item["slot_at"][:10]
    slot = {"i": 0, "date": d, "weekday": WEEKDAY_PT[date.fromisoformat(d).weekday()], "time": item["slot_at"][11:16],
            "format": item["format"], "datas": [x["nome"] for x in dates if x["date"] == d]}
    others = [x["title"] for x in plan["items"] if x["id"] != item_id and x.get("title")]
    used: Dict[str, int] = {}
    for x in plan["items"]:
        if x["id"] != item_id and x.get("product") and x.get("stage") != "idea_rejected":
            used[x["product"]] = used.get(x["product"], 0) + 1
    near = [x for x in plan["items"] if x["id"] != item_id and abs((date.fromisoformat(x["slot_at"][:10]) - date.fromisoformat(d)).days) <= 2]
    extra = ("REFAÇA esta peça. Versão anterior (NÃO repita): " + (item.get("title") or "") + " — " + (item.get("angle") or "")
             + "\nUSO DE PRODUTOS NO MÊS: " + (", ".join(f"{k} ({v})" for k, v in sorted(used.items(), key=lambda x: x[1])) or "nenhum")
             + "\nPEÇAS VIZINHAS (não repita produto nem tema delas): "
             + "; ".join(f"{x['slot_at'][:10]} {x.get('product') or 'institucional'}: {x.get('title')}" for x in near)
             + (f"\nPEDIDO DO APROVADOR (obedeça; ele tem prioridade sobre as regras de rodízio): {comment}" if comment else ""))
    items = _ai_fill(company, cfg, dates, [slot], others + recent_titles(company["id"], exclude_plan=plan["id"]), extra)
    row = _norm_item(items[0] if items else {}, slot, [p["name"] for p in product_list(company["id"]) or []])
    row.update(stage="idea", review_comment=comment or None, error=None if row["title"] else "A IA não respondeu — tente de novo.")
    return item_update(item_id, row)


# ═════════════════════════════ MARCO B — produção das artes + agendamento ═════════════════════════════
# Etapas da peça: idea → idea_ok → art_queued → producing → art (arte para aprovar) → art_ok (aprovada, esperando
# Instagram) → scheduled → published | failed. Também: idea_rejected, art_rejected, skipped (passou da data sem OK).
# As chamadas internas usam a PRÓPRIA API (mesmo caminho da tela: briefing → Estúdio IA → post → Publicar).

_API = "http://127.0.0.1:8765"
_TZ = "-03:00"                                   # horário de Brasília (sem horário de verão desde 2019)
_WORKER: Dict[str, Any] = {"task": None}
FORMAT_RENDER = {"post": "post", "carrossel": "carrossel", "reels": "story"}


def _headers() -> Dict[str, str]:
    from ..main_utils import _get_api_key
    return {"X-API-Key": _get_api_key(), "Content-Type": "application/json"}


async def _api(method: str, path: str, body: Optional[Dict[str, Any]] = None, timeout: float = 120.0) -> Dict[str, Any]:
    import httpx
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as c:
        r = await c.request(method, _API + path, headers=_headers(), json=body)
    try:
        data = r.json()
    except Exception:
        data = {"detail": r.text[:300]}
    if r.status_code >= 400:
        raise ValueError((data.get("detail") if isinstance(data, dict) else None) or f"HTTP {r.status_code}")
    return data


def slot_iso(item: Dict[str, Any]) -> str:
    return (item.get("slot_at") or "")[:19] + _TZ


def _slot_dt(item: Dict[str, Any]) -> datetime:
    return datetime.fromisoformat(slot_iso(item))


def items_by_stage(stages: List[str], company_id: Optional[str] = None) -> List[Dict[str, Any]]:
    q = f"SELECT * FROM editorial_items WHERE stage IN ({','.join('?' for _ in stages)})"
    args: List[Any] = list(stages)
    if company_id:
        q += " AND company_id = ?"
        args.append(company_id)
    with get_conn() as conn:
        return [_row(r) for r in conn.execute(q + " ORDER BY slot_at", args).fetchall()]


def _offer_refs_for(company_id: str, product: str) -> List[Dict[str, str]]:
    if not product:
        return []
    from ..db_companies import product_list
    p = next((x for x in product_list(company_id) or [] if (x.get("name") or "").lower() == product.lower()), None)
    return [{"source_company_id": company_id, "product_id": p["id"]}] if p else []


async def produce_item(item_id: str) -> None:
    """Gera a arte de UMA peça aprovada: telas pelo gerador aprovado (generate-briefing) + Estúdio IA (render-carousel).
    A legenda aprovada no calendário substitui a gerada pelo render."""
    item = item_get(item_id)
    if not item or item["stage"] not in ("art_queued", "producing"):
        return
    item_update(item_id, {"stage": "producing", "error": None})
    fmt = FORMAT_RENDER.get(item["format"], "post")
    offers = _offer_refs_for(item["company_id"], item.get("product") or "")
    theme = (item.get("title") or "").strip()
    idea = " ".join(x for x in [item.get("angle"), ("Direção de arte: " + item["art_brief"]) if item.get("art_brief") else "",
                                ("Pedido do aprovador: " + item["review_comment"]) if item.get("review_comment") else ""] if x)
    try:
        telas, last_err = [], None
        for _att in range(3):          # o gerador de telas às vezes devolve JSON quebrado → tenta de novo
            try:
                br = await _api("POST", "/api/posts/generate-briefing", {
                    "company_id": item["company_id"], "theme": theme, "idea": idea[:1800], "objetivo": "vender",
                    "formato": fmt, "n_telas": 0 if fmt == "carrossel" else 1, "intent": "produtos",
                    "apps": [item["product"]] if item.get("product") else [], "offer_refs": offers}, timeout=300)
                telas = br.get("telas") or []
                if telas or fmt != "carrossel":
                    break
            except Exception as exc:
                last_err = exc
                await asyncio.sleep(10 * (_att + 1))
        if fmt != "carrossel":
            telas = telas[:1] or [{"type": "cover", "title": theme[:64]}]
        if not telas:
            raise ValueError(f"o gerador não devolveu as telas ({last_err or 'vazio'})")
        if theme:
            telas[0] = dict(telas[0], title=theme)    # capa = título APROVADO no calendário
        rr = await _api("POST", "/api/posts/render-carousel", {
            "company_id": item["company_id"], "telas": telas, "model": "", "format": fmt,
            "render_mode": "reference_full", "offer_refs": offers}, timeout=1800)
        slides = [s.get("url") for s in (rr.get("slides") or []) if s.get("url")]
        if not slides:
            raise ValueError(rr.get("warning") or "nenhuma imagem gerada")
        post_id = rr.get("post_id")
        if post_id:
            from ..db_companies import post_update
            post_update(post_id, {"copy": item.get("copy") or "", "hashtags": item.get("hashtags") or "",
                                  "title": theme or None})
        meta = dict(item.get("meta") or {})
        meta.update({"slides": slides, "telas": telas, "art_warning": rr.get("warning") or "", "art_cost": rr.get("cost") or 0})
        item_update(item_id, {"stage": "art", "post_id": post_id, "meta": meta, "error": None})
    except Exception as exc:
        log.exception("agency produce %s", item_id)
        item_update(item_id, {"stage": "idea_ok", "error": f"Falha ao gerar a arte: {str(exc)[:300]}"})


async def _worker_loop() -> None:
    try:
        while True:
            queue = items_by_stage(["art_queued", "producing"])
            if not queue:
                return
            await produce_item(queue[0]["id"])
    finally:
        _WORKER["task"] = None


def ensure_worker() -> bool:
    t = _WORKER.get("task")
    if t and not t.done():
        return False
    _WORKER["task"] = asyncio.create_task(_worker_loop())
    return True


def queue_production(plan_id: str, item_ids: Optional[List[str]] = None) -> int:
    plan = plan_get(plan_id)
    n = 0
    for it in plan["items"]:
        if item_ids and it["id"] not in item_ids:
            continue
        if it["stage"] in ("idea_ok", "art_rejected") or (item_ids and it["stage"] == "art"):
            item_update(it["id"], {"stage": "art_queued", "error": None})
            n += 1
    if n:
        ensure_worker()
    return n


async def approve_art(item_id: str) -> Dict[str, Any]:
    """Arte aprovada → post APPROVED com data do calendário → agenda no Instagram (se conectado)."""
    from ..db_companies import post_get, post_transition, post_update
    item = item_get(item_id)
    if not item or item["stage"] not in ("art", "art_ok"):
        raise ValueError("A peça não está com arte pronta para aprovar.")
    post = post_get(item["post_id"]) if item.get("post_id") else None
    if not post:
        raise ValueError("Post da arte não encontrado — gere a arte de novo.")
    when = _slot_dt(item)
    if when <= datetime.now(timezone.utc) + timedelta(minutes=10):
        when = datetime.now(timezone.utc) + timedelta(minutes=15)     # data já passou → publica em 15 min
    post_update(post["id"], {"scheduled_at": when.isoformat(), "copy": item.get("copy") or post.get("copy") or "",
                             "hashtags": item.get("hashtags") or post.get("hashtags") or ""})
    if post.get("status") == "DRAFT":
        post_transition(post["id"], "REVIEW")
    if (post_get(post["id"]) or {}).get("status") == "REVIEW":
        post_transition(post["id"], "APPROVED")
    item_update(item_id, {"stage": "art_ok", "error": None})
    return await schedule_item(item_id)


async def schedule_item(item_id: str) -> Dict[str, Any]:
    """Cria o agendamento social (cron social_publish_scheduled publica na hora). Sem Instagram conectado →
    fica 'art_ok' e o tick agenda sozinho quando a conta for conectada."""
    from ..db_agency import social_connection_list
    from ..db_companies import post_get, post_transition
    item = item_get(item_id)
    post = post_get(item["post_id"])
    conns = [c for c in social_connection_list(brand_id=item["company_id"], platform="instagram")
             if c.get("status") in ("connected", "active")]
    if not conns:
        return item_update(item_id, {"error": "Arte aprovada. Aguardando o Instagram ser conectado para agendar."})
    urls = (item.get("meta") or {}).get("slides") or []
    from ..routers.posts import _render_public_base
    abs_urls = [(_render_public_base() + u) if u.startswith("/") else u for u in urls]
    ctype = "carousel" if len(abs_urls) > 1 else ("story" if item["format"] == "reels" else "image")
    try:
        r = await _api("POST", "/api/social/posts", {
            "brandId": item["company_id"], "sourcePostId": post["id"],
            "channels": [{"socialConnectionId": conns[0]["id"]}], "assetUrls": abs_urls, "contentType": ctype,
            "scheduledAt": post.get("scheduled_at"), "approved": True})
    except Exception as exc:
        return item_update(item_id, {"error": f"Não consegui agendar no Instagram: {str(exc)[:240]}"})
    sp = (r.get("post") or {})
    if post.get("status") == "APPROVED":
        post_transition(post["id"], "SCHEDULED")
    return item_update(item_id, {"stage": "scheduled", "social_post_id": sp.get("id"), "error": None})


# ═════════════════════════════ MARCO D — piloto automático ═════════════════════════════

def _app_link() -> str:
    from ..routers.posts import _render_public_base
    return _render_public_base() + "/os/index.html"


async def _notify(company: Dict[str, Any], cfg: Dict[str, Any], text: str, trigger: str) -> None:
    to = (cfg.get("notify_whatsapp") or "").strip()
    if not to:
        log.info("agency notify (%s) sem WhatsApp configurado: %s", company.get("name"), text[:120])
        return
    try:
        from .notifier import notify
        await notify(company_id=company["id"], channel="whatsapp", recipient=to,
                     subject="Agência Caripost", message=text, trigger=trigger)
    except Exception as exc:
        log.warning("agency notify falhou: %s", exc)


def _companies_enabled() -> List[Dict[str, Any]]:
    from ..db_companies import company_get, company_list
    out = []
    for c in company_list() or []:
        co = company_get(c["id"])
        if co and agency_cfg(co).get("enabled"):
            out.append(co)
    return out


def _next_month_str(today: Optional[date] = None) -> str:
    t = today or datetime.now().date()
    return f"{t.year + (t.month == 12):04d}-{(t.month % 12) + 1:02d}"


async def monthly_job(force_day: Optional[int] = None) -> List[str]:
    """Dia configurado (padrão 20): gera o calendário do mês seguinte p/ quem tem a agência ligada e avisa."""
    today = datetime.now().date()
    done = []
    for co in _companies_enabled():
        cfg = agency_cfg(co)
        day = int(force_day or cfg.get("generate_day") or 20)
        if today.day != day:
            continue
        month = _next_month_str(today)
        if any(p["month"] == month for p in plan_list(co["id"])):
            continue
        y, m = map(int, month.split("-"))
        if not build_slots(y, m, cfg, month_dates(y, m, co)):
            continue
        plan = plan_create(co["id"], month, cfg)
        try:
            await asyncio.to_thread(_generate_plan_sync, plan["id"])
        except Exception as exc:
            plan_update(plan["id"], status="error", error=str(exc)[:500])
            continue
        n = len(plan_get(plan["id"])["items"])
        await _notify(co, cfg, f"Agência Caripost: o calendário de {month} da {co['name']} está pronto — {n} ideias "
                               f"esperando sua aprovação no app Agência: {_app_link()}", "agency_month_ready")
        done.append(co["name"])
    return done


async def tick() -> Dict[str, int]:
    """A cada poucos minutos: retoma a fila de artes, agenda aprovadas quando o Instagram conectar, sincroniza
    publicação, lembra artes pendentes (48h) e marca como 'pulada' peça que passou da data sem aprovação."""
    stats = {"resumed": 0, "scheduled": 0, "published": 0, "failed": 0, "reminded": 0, "skipped": 0}
    if items_by_stage(["art_queued", "producing"]) and ensure_worker():
        stats["resumed"] = 1
    now = datetime.now(timezone.utc)
    for it in items_by_stage(["art_ok"]):
        before = it.get("stage")
        out = await schedule_item(it["id"])
        if out and out.get("stage") == "scheduled" and before != "scheduled":
            stats["scheduled"] += 1
    from ..db_agency import social_post_get
    from ..db_companies import company_get
    for it in items_by_stage(["scheduled"]):
        sp = social_post_get(it["social_post_id"]) if it.get("social_post_id") else None
        st = (sp or {}).get("status")
        if st == "published":
            item_update(it["id"], {"stage": "published", "error": None}); stats["published"] += 1
        elif st in ("failed", "partial_failed"):
            errs = "; ".join(c.get("error_message") or "" for c in (sp.get("channels") or []) if c.get("error_message"))
            item_update(it["id"], {"stage": "failed", "error": "Instagram recusou: " + (errs or st)})
            co = company_get(it["company_id"])
            await _notify(co, agency_cfg(co), f"Agência Caripost: a peça '{it.get('title')}' NÃO foi publicada "
                                              f"({(errs or st)[:160]}). Veja no app Agência.", "agency_publish_failed")
            stats["failed"] += 1
    pending = items_by_stage(["idea", "idea_ok", "art_queued", "art"])
    for it in pending:
        when = _slot_dt(it)
        meta = dict(it.get("meta") or {})
        if when < now:
            item_update(it["id"], {"stage": "skipped", "error": "Passou da data sem aprovação — não foi publicada."})
            stats["skipped"] += 1
        elif it["stage"] == "art" and when - now < timedelta(hours=48) and not meta.get("reminded"):
            meta["reminded"] = _now()
            item_update(it["id"], {"meta": meta})
            co = company_get(it["company_id"])
            await _notify(co, agency_cfg(co), f"Agência Caripost: a arte '{it.get('title')}' sai em "
                                              f"{when.astimezone(timezone(timedelta(hours=-3))).strftime('%d/%m %H:%M')} "
                                              f"e ainda precisa da sua aprovação: {_app_link()}", "agency_reminder")
            stats["reminded"] += 1
    return stats


# ═════════════════════════════ MULTI-CLIENTE ═════════════════════════════

def suggest_config(company: Dict[str, Any]) -> Dict[str, Any]:
    """Pilares/pesos, estilo, CTA e hashtags SOB MEDIDA para o cliente, a partir do cadastro (público, voz,
    segmento, catálogo). Usado no 1º calendário de quem ainda não configurou e no botão 'Sugerir com IA'."""
    from .ai import complete_ai, extract_json, get_ai_config
    bk = company.get("brand_kit") or {}
    socials = company.get("socials") or {}
    user = (
        f"EMPRESA: {company.get('name')} — segmento: {company.get('segment') or ''}. Site: {company.get('website') or ''}. "
        f"Instagram: {socials.get('instagram') or ''}.\n"
        f"PÚBLICO: {(bk.get('audience') or '').strip()}\nVOZ: {(bk.get('voice') or '').strip()}\n"
        f"PERSONA: {(bk.get('persona') or '').strip()[:500]}\n"
        f"CATÁLOGO:\n{_catalog_context(company)[:5000]}\n\n"
        "Monte a linha editorial do Instagram desta empresa como uma agência faria. Responda SÓ JSON:\n"
        '{"pillars":[{"name":"<pilar curto>","weight":<inteiro>,"desc":"<o que entra neste pilar, falando com o público certo>"}],'
        '"style":"<guia de legenda: gancho, estrutura, tom, CTA, hashtags — 3 a 5 frases>",'
        '"cta":"<CTA padrão curto>","hashtags_base":["#a","#b"]}\n'
        "Regras: 4 pilares, pesos somando 100; um pilar de produto/serviço do catálogo, um de educação/valor para o "
        "público, um de datas/eventos e um de relacionamento/autoridade/prova social (adapte nomes ao negócio). "
        "Se o público for consumidor final, fale com ele; se for B2B, fale com o decisor. 5–8 hashtags.")
    data = extract_json(complete_ai(get_ai_config(), "Você é estrategista de social media. Responda somente JSON válido.",
                                    user, 2000)) or {}
    out: Dict[str, Any] = {}
    pills = [p for p in (data.get("pillars") or []) if isinstance(p, dict) and p.get("name")][:6]
    if pills:
        tot = sum(int(p.get("weight") or 0) for p in pills) or 100
        out["pillars"] = [{"name": str(p["name"])[:60], "weight": round(int(p.get("weight") or 0) * 100 / tot),
                           "desc": str(p.get("desc") or "")[:400]} for p in pills]
    for k in ("style", "cta"):
        if isinstance(data.get(k), str) and data[k].strip():
            out[k] = data[k].strip()[:1200]
    tags = [t if str(t).startswith("#") else "#" + str(t) for t in (data.get("hashtags_base") or []) if str(t).strip()]
    if tags:
        out["hashtags_base"] = tags[:10]
    phone = "".join(ch for ch in (company.get("phone") or "") if ch.isdigit())
    if phone and len(phone) >= 10:
        out.setdefault("whatsapp", company.get("phone"))
    return out


def ensure_tailored_config(company_id: str) -> Dict[str, Any]:
    """Cliente sem linha editorial própria → gera e SALVA a sugestão antes do 1º calendário."""
    from ..db_companies import brand_kit_upsert, company_get
    co = company_get(company_id)
    cc = dict(((co.get("brand_kit") or {}).get("creative_config")) or {})
    ov = dict(cc.get("agency") or {})
    if ov.get("pillars") and ov.get("style"):
        return agency_cfg(co)
    sug = suggest_config(co)
    if not sug.get("pillars"):
        raise ValueError("a IA não devolveu os pilares")
    for k, v in sug.items():
        ov.setdefault(k, v)
    ov["auto_tailored_at"] = _now()
    cc["agency"] = ov
    brand_kit_upsert(company_id, {"creative_config": cc})
    return agency_cfg(company_get(company_id))


def overview(company_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Painel da agência: todos os clientes (do escopo) com o estado do mês."""
    from ..db_companies import company_get, company_list
    nm = _next_month_str()
    out = []
    for c in company_list() or []:
        if company_ids is not None and str(c["id"]) not in company_ids:
            continue
        co = company_get(c["id"]) or c
        cfg = agency_cfg(co)
        plans = plan_list(c["id"])
        cur = plans[0] if plans else None
        counts: Dict[str, int] = {}
        if cur:
            for it in plan_get(cur["id"])["items"]:
                counts[it["stage"]] = counts.get(it["stage"], 0) + 1
        out.append({
            "company_id": c["id"], "name": c.get("name"), "lifecycle_stage": c.get("lifecycle_stage"),
            "enabled": bool(cfg.get("enabled")), "tailored": bool(((co.get("brand_kit") or {}).get("creative_config") or {}).get("agency", {}).get("pillars")),
            "plan": ({"id": cur["id"], "month": cur["month"], "status": cur["status"], "n_items": cur.get("n_items")} if cur else None),
            "has_next_month": any(p["month"] == nm for p in plans), "counts": counts,
        })
    out.sort(key=lambda x: (not x["enabled"], not x["plan"], (x["name"] or "").lower()))
    return out
