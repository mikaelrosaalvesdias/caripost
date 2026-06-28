"""
Notify + public approval router.

- /api/notify/config   (GET/POST)  — Evolution (WhatsApp) + SMTP settings
- /api/notify/test     (POST)      — send a test message (test function-by-function)
- /api/approvals/link  (POST)      — create a public approval link (token)
- /approval/{token}    (GET)       — public white-label approval page (no auth)
- /api/approval/{token}/data (GET) — public JSON for the page
- /api/approval/{token}/decide (POST) — public decision (approve / changes + comment)
"""
from __future__ import annotations

import html as _html
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter(tags=["notify"])


def _auth(request: Request):
    from ..main_utils import require_api_key
    return require_api_key(request)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Config ─────────────────────────────────────────────────────────────────────

@router.get("/api/notify/config")
def get_config(request: Request):
    err = _auth(request)
    if err:
        return err
    from ..services.notifier import config_status
    return config_status()


@router.post("/api/notify/config")
async def save_config(request: Request):
    err = _auth(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        body = {}
    from ..db import settings_set
    from ..security.encryption import encrypt

    def _set(key, value):
        settings_set(key=key, value=str(value or ""), updated_at=_now())

    def _set_secret(key, value):
        if value:
            settings_set(key=key, value=encrypt(str(value)) or str(value), updated_at=_now())

    evo = body.get("evolution") or {}
    if "url" in evo: _set("notify.evolution.url", evo.get("url"))
    if "instance" in evo: _set("notify.evolution.instance", evo.get("instance"))
    if evo.get("apiKey"): _set_secret("notify.evolution.apiKey", evo.get("apiKey"))

    smtp = body.get("smtp") or {}
    for k in ("host", "port", "user", "from", "fromName", "tls"):
        if k in smtp:
            _set(f"notify.smtp.{k}", smtp.get(k))
    if smtp.get("pass"):
        _set_secret("notify.smtp.pass", smtp.get("pass"))

    from ..services.notifier import config_status
    return {"ok": True, "status": config_status()}


@router.post("/api/notify/test")
async def test_send(request: Request):
    err = _auth(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        body = {}
    channel = (body.get("channel") or "whatsapp").strip()
    to = (body.get("to") or "").strip()
    message = body.get("message") or "Teste de notificação do Caripost ✅"
    if not to:
        return JSONResponse({"detail": "Informe o destinatário (número ou e-mail)."}, status_code=422)
    from ..services.notifier import notify
    result = await notify(company_id=body.get("company_id") or "", channel=channel, recipient=to,
                          subject="Teste Caripost", message=message, trigger="test")
    return result if result.get("ok") else JSONResponse(result, status_code=502)


# ── Public approval links ──────────────────────────────────────────────────────

def _public_base(request: Request) -> str:
    import os
    base = (os.environ.get("APP_PUBLIC_URL") or "").strip().rstrip("/")
    if not base:
        try:
            from ..db import get_setting
            base = (get_setting("telegram:app_public_url") or "").strip().rstrip("/")
        except Exception:
            base = ""
    if not base:
        base = "https://caripost.cariap.com.br"          # fallback de produção (evita link interno/404)
    if base.startswith("http://"):
        base = "https://" + base[7:]                      # força https (proxy às vezes reporta http → "não seguro")
    return base


@router.post("/api/approvals/link")
async def create_link(request: Request):
    err = _auth(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        body = {}
    company_id = body.get("company_id") or body.get("brandId")
    post_ids = body.get("post_ids") or []
    if not company_id:
        return JSONResponse({"detail": "company_id é obrigatório"}, status_code=422)
    hours = int(body.get("expires_hours") or 168)  # default 7 days
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    from ..db_companies import approval_link_create
    link = approval_link_create(company_id, post_ids, stage=body.get("stage") or "client", expires_at=expires_at)
    url = _public_base(request) + "/approval/" + link["token"]
    return {"link": link, "url": url}


def _link_valid(link) -> Optional[str]:
    if not link:
        return "Link inválido."
    if link.get("status") == "revoked":
        return "Link revogado."
    exp = link.get("expires_at")
    if exp:
        try:
            if datetime.fromisoformat(exp) < datetime.now(timezone.utc):
                return "Link expirado."
        except Exception:
            pass
    return None


@router.get("/api/approval/{token}/data")
def approval_data(token: str):
    from ..db_companies import approval_link_get, company_get, post_get, post_list
    link = approval_link_get(token)
    invalid = _link_valid(link)
    if invalid:
        return JSONResponse({"detail": invalid}, status_code=410)
    company = company_get(link["company_id"]) or {}
    ids = link.get("post_ids") or []
    if ids:
        posts = [p for p in (post_get(i) for i in ids) if p]
    else:
        posts = post_list(statuses=["REVIEW"], company_id=link["company_id"], limit=100)
    bk = company.get("brand_kit") or {}
    return {
        "company": {"name": company.get("name") or "Aprovação", "logo": bk.get("logo_url") or ""},
        "stage": link.get("stage"),
        "posts": [{
            "id": p.get("id"), "title": p.get("title"), "copy": p.get("copy"),
            "hashtags": p.get("hashtags"), "networks": p.get("networks"),
            "status": p.get("status"), "media_url": p.get("media_url") or "",
            "carousel_urls": ((p.get("meta") or {}).get("carousel_urls")) or [],
            "content_type": (p.get("meta") or {}).get("content_type") or "",
        } for p in posts],
    }


@router.post("/api/approval/{token}/decide")
async def approval_decide(token: str, request: Request):
    from ..db_companies import approval_link_get, post_get, post_transition, post_update, notifications_log_create
    link = approval_link_get(token)
    invalid = _link_valid(link)
    if invalid:
        return JSONResponse({"detail": invalid}, status_code=410)
    try:
        body = await request.json()
    except Exception:
        body = {}
    decision = (body.get("decision") or "").strip()  # approve | changes | reject
    if decision not in ("approve", "changes", "reject"):
        return JSONResponse({"detail": "Decisão inválida."}, status_code=422)
    comment = (body.get("comment") or "").strip()
    if decision in ("changes", "reject") and not comment:
        return JSONResponse({"detail": "Descreva o que precisa ser ajustado."}, status_code=422)
    post_id = body.get("post_id")
    targets = [post_id] if post_id else (link.get("post_ids") or [])
    if not targets:
        return JSONResponse({"detail": "Nada para decidir."}, status_code=422)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    done = []
    for pid in targets:
        p = post_get(pid)
        if not p or p.get("company_id") != link["company_id"]:
            continue
        if decision == "approve":
            post_update(pid, {"review_decision": "approved", "review_comment": "", "reviewed_at": now})
            post_transition(pid, "APPROVED") or post_update(pid, {"status": "APPROVED"})
        else:
            # changes (aprovado com ressalvas) / reject (reprovado): volta pro time com a devolutiva
            post_update(pid, {"review_decision": ("rejected" if decision == "reject" else "changes"),
                              "review_comment": comment, "reviewed_at": now})
        done.append(pid)
        try:
            notifications_log_create({
                "company_id": link["company_id"], "channel": "approval_page",
                "trigger": f"client_{decision}", "recipient": "cliente",
                "status": "sent", "detail": (comment or "")[:300],
            })
        except Exception:
            pass
    # Aprendizado por cliente: reprovação com motivo vira REGRA permanente da marca,
    # injetada nos prompts futuros pra nunca repetir o erro com este cliente.
    if decision == "reject" and comment and done:
        try:
            from ..db_companies import company_get, brand_kit_upsert
            co = company_get(link["company_id"]) or {}
            bk = co.get("brand_kit") or {}
            rules = (bk.get("client_rules") or "").strip()
            new_rule = f"- {comment.strip()}"
            if new_rule.lower() not in rules.lower():
                rules = (rules + "\n" + new_rule).strip()
                brand_kit_upsert(link["company_id"], {"client_rules": rules[:4000]})
        except Exception:
            pass
    return {"ok": True, "decided": done, "decision": decision}


# ── Public page (white-label, no shell, no auth) ───────────────────────────────

@router.get("/approval/{token}")
def approval_page(token: str):
    safe = _html.escape(token)
    page = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aprovação de conteúdo</title>
<style>
:root{--bg:#fafafa;--card:#fff;--line:#dbdbdb;--blue:#0095f6;--good:#2e9a3e;--warn:#e0a000;--bad:#ed4956;--fg:#262626;--muted:#8e8e8e}
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--fg)}
header{display:flex;gap:12px;align-items:center;justify-content:center;padding:16px;border-bottom:1px solid var(--line);background:#fff;position:sticky;top:0;z-index:5}
header img{height:30px;border-radius:6px}header h1{font-size:16px;margin:0;font-weight:600}
.wrap{max-width:480px;margin:0 auto;padding:18px 12px 60px}
.intro{font-size:13px;color:var(--muted);text-align:center;margin:6px 0 18px}
.ig{background:var(--card);border:1px solid var(--line);border-radius:10px 10px 0 0;margin-bottom:0;overflow:hidden}
.igh{display:flex;align-items:center;gap:10px;padding:10px 12px}
.av{width:34px;height:34px;border-radius:50%;background:linear-gradient(45deg,#f09433,#dc2743,#bc1888);display:grid;place-items:center;color:#fff;font-weight:700;font-size:14px;overflow:hidden;flex:none}
.av img{width:100%;height:100%;object-fit:cover}
.un{font-weight:600;font-size:14px}.dots{margin-left:auto;font-weight:700}
.igm{width:100%;display:block;background:#000}.igm img,.igm video{width:100%;display:block}
.acts{display:flex;gap:14px;padding:8px 12px 2px;font-size:20px}.acts .sp{margin-left:auto}
.likes{padding:2px 12px;font-weight:600;font-size:14px}
.cap{padding:4px 12px 12px;font-size:14px;line-height:1.4;white-space:pre-wrap}.cap b{font-weight:600}.tags{color:#00376b}
.time{padding:0 12px 12px;color:var(--muted);font-size:11px;text-transform:uppercase}
.dec{background:var(--card);border:1px solid var(--line);border-top:none;border-radius:0 0 10px 10px;margin:0 0 18px;padding:12px}
.row{display:flex;gap:8px;flex-wrap:wrap}
.btn{flex:1;min-width:120px;border:none;border-radius:8px;padding:11px;font-weight:700;cursor:pointer;font-size:13px;color:#fff}
.b-ap{background:var(--good)}.b-rv{background:var(--warn)}.b-rj{background:var(--bad)}
textarea{width:100%;margin-top:10px;border:1px solid var(--line);border-radius:8px;padding:10px;resize:vertical;font:inherit}
.send{margin-top:8px;background:var(--blue);color:#fff;border:none;border-radius:8px;padding:10px 16px;font-weight:700;cursor:pointer}
.st{font-size:13px;margin-top:8px;font-weight:600}.st.ok{color:var(--good)}.st.er{color:var(--bad)}
.hide{display:none}.done{opacity:.55}.msg{padding:10px 14px;border-radius:8px;margin-bottom:14px}.merr{background:#ffe9e9;color:#c0392b}
.car{position:relative}.track{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;scrollbar-width:none}.track::-webkit-scrollbar{display:none}.track img{width:100%;flex:none;scroll-snap-align:center;display:block}
.cnt{position:absolute;top:10px;right:10px;background:rgba(0,0,0,.65);color:#fff;font-size:12px;font-weight:700;padding:3px 9px;border-radius:12px}
.dots2{position:absolute;bottom:10px;left:0;right:0;display:flex;gap:5px;justify-content:center}.dots2 .dot{width:6px;height:6px;border-radius:50%;background:rgba(255,255,255,.5)}.dots2 .dot.on{background:#fff}
.swh{position:absolute;top:50%;transform:translateY(-50%);background:rgba(0,0,0,.4);color:#fff;border:none;width:34px;height:34px;border-radius:50%;font-size:18px;cursor:pointer}.swh.l{left:8px}.swh.r{right:8px}
</style></head><body>
<header><div id="logo"></div><h1 id="title">Aprovação de conteúdo</h1></header>
<div class="wrap"><div class="intro">Arraste o carrossel pra ver todas as telas. Decida: aprovar 100%, aprovar com ressalvas (diga qual tela) ou reprovar.</div><div id="msg"></div><div id="list" class="intro">Carregando…</div></div>
<script>
const TOKEN=%TOKEN%;
const $=s=>document.querySelector(s);
let CURDEC={},CURSLIDE={};
function sw(btn,dir){const tr=btn.closest('.car').querySelector('.track');tr.scrollBy({left:dir*tr.clientWidth,behavior:'smooth'});}
function esc(t){const d=document.createElement('div');d.textContent=t==null?'':t;return d.innerHTML;}
function linkTags(t){return esc(t).replace(/#(\\w+)/g,'<span class="tags">#$1</span>');}
async function load(){
  let r;try{r=await fetch('/api/approval/'+TOKEN+'/data');}catch(e){$('#list').innerHTML='<div class="merr msg">Erro de rede.</div>';return;}
  if(!r.ok){const e=await r.json().catch(()=>({}));$('#list').innerHTML='<div class="merr msg">'+esc(e.detail||'Link inválido')+'</div>';return;}
  const d=await r.json();
  const name=d.company.name||'';
  const handle=(name||'perfil').toLowerCase().replace(/[^a-z0-9]/g,'')||'perfil';
  $('#title').textContent='Aprovação · '+name;
  if(d.company.logo)$('#logo').innerHTML='<img src="'+esc(d.company.logo)+'">';
  if(!d.posts.length){$('#list').innerHTML='<div class="intro">Nada para aprovar.</div>';return;}
  const initial=(name||'P').trim().charAt(0).toUpperCase();
  const avatar=d.company.logo?('<img src="'+esc(d.company.logo)+'">'):esc(initial);
  $('#list').innerHTML=d.posts.map(p=>{
    const urls=(p.carousel_urls&&p.carousel_urls.length)?p.carousel_urls:(p.media_url?[p.media_url]:[]);
    let media;
    if(urls.length>1){
      const slides=urls.map(u=>'<img src="'+esc(u)+'" loading="lazy">').join('');
      const dots=urls.map((u,i)=>'<span class="dot'+(i?'':' on')+'"></span>').join('');
      media='<div class="car"><div class="track" data-id="'+esc(p.id)+'">'+slides+'</div>'
        +'<button class="swh l" onclick="sw(this,-1)">\\u2039</button><button class="swh r" onclick="sw(this,1)">\\u203a</button>'
        +'<div class="cnt">1/'+urls.length+'</div><div class="dots2">'+dots+'</div></div>';
    }else if(urls.length===1){
      media=(urls[0]||'').toLowerCase().endsWith('.mp4')?'<video src="'+esc(urls[0])+'" controls></video>':'<img src="'+esc(urls[0])+'">';
    }else{media='<div style="padding:50px 12px;text-align:center;color:#fff">sem m\\u00eddia</div>';}
    const cap=esc(p.copy||'');
    const tags=p.hashtags?'<div class="tags" style="margin-top:6px">'+linkTags(p.hashtags)+'</div>':'';
    return '<div class="ig">'
      +'<div class="igh"><div class="av">'+avatar+'</div><div class="un">'+esc(handle)+'</div><div class="dots">\\u22ef</div></div>'
      +'<div class="igm">'+media+'</div>'
      +'<div class="acts">\\u2661 \\uD83D\\uDCAC \\u21AA<span class="sp">\\uD83D\\uDD16</span></div>'
      +'<div class="likes">Pr\\u00e9-visualiza\\u00e7\\u00e3o do post</div>'
      +'<div class="cap"><b>'+esc(handle)+'</b> '+cap+tags+'</div>'
      +'<div class="time">'+esc((p.networks||['instagram']).join(' \\u00b7 '))+'</div></div>'
      +'<div class="dec" data-id="'+esc(p.id)+'">'
      +'<div class="row"><button class="btn b-ap" onclick="approve(this)">\\u2713 Aprovar 100%</button>'
      +'<button class="btn b-rv" onclick="openBox(this,\\'changes\\')">\\u270E Com ressalvas</button>'
      +'<button class="btn b-rj" onclick="openBox(this,\\'reject\\')">\\u2715 Reprovar</button></div>'
      +'<div class="box hide"><textarea rows="3" placeholder="O que ajustar? (vale para a TELA aberta no carrossel \\u2014 arraste at\\u00e9 ela antes)"></textarea>'
      +'<button class="send" onclick="sendBox(this)">Enviar devolutiva</button></div>'
      +'<div class="st"></div></div>';
  }).join('');
  document.querySelectorAll('.track').forEach(function(tr){
    const car=tr.parentElement,cnt=car.querySelector('.cnt'),dots=car.querySelectorAll('.dot'),n=tr.children.length;
    tr.addEventListener('scroll',function(){const i=Math.round(tr.scrollLeft/Math.max(1,tr.clientWidth));cnt.textContent=(i+1)+'/'+n;dots.forEach((d,k)=>d.classList.toggle('on',k===i));CURSLIDE[tr.getAttribute('data-id')]=i+1;},{passive:true});
  });
}
function setSt(dec,txt,ok){const s=dec.querySelector('.st');s.textContent=txt;s.className='st '+(ok?'ok':'er');}
function lock(dec){dec.classList.add('done');dec.querySelectorAll('button,textarea').forEach(b=>b.disabled=true);}
async function post(id,decision,comment){
  const r=await fetch('/api/approval/'+TOKEN+'/decide',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({post_id:id,decision,comment})});
  const d=await r.json().catch(()=>({}));return{ok:r.ok,d};
}
async function approve(btn){const dec=btn.closest('.dec');setSt(dec,'Enviando\\u2026',true);
  const res=await post(dec.getAttribute('data-id'),'approve','');
  if(res.ok){setSt(dec,'\\u2713 Aprovado 100%',true);lock(dec);}else setSt(dec,'Erro: '+(res.d.detail||''),false);}
function openBox(btn,decision){const dec=btn.closest('.dec');CURDEC[dec.getAttribute('data-id')]=decision;
  dec.querySelector('.box').classList.remove('hide');dec.querySelector('textarea').focus();
  setSt(dec,decision==='reject'?'Diga o motivo da reprova\\u00e7\\u00e3o e envie:':'Diga o que ajustar e envie:',true);}
async function sendBox(btn){const dec=btn.closest('.dec');const id=dec.getAttribute('data-id');
  const comment=dec.querySelector('textarea').value.trim();
  if(!comment){setSt(dec,'Escreva a devolutiva.',false);return;}
  const sl=CURSLIDE[id];const full=(sl?('Tela '+sl+': '):'')+comment;
  setSt(dec,'Enviando\\u2026',true);
  const res=await post(id,CURDEC[id]||'changes',full);
  if(res.ok){setSt(dec,CURDEC[id]==='reject'?'\\u2715 Reprovado \\u2014 devolutiva enviada':'\\u270E Aprovado com ressalvas \\u2014 enviado',true);lock(dec);}else setSt(dec,'Erro: '+(res.d.detail||''),false);}
load();
</script></body></html>"""
    page = page.replace("%TOKEN%", json.dumps(safe))
    return HTMLResponse(page)
