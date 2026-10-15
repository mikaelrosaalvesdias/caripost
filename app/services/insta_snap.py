"""Importa artes de posts PÚBLICOS do Instagram sem login e sem credencial do cliente (out/2026).

Caminho: link do post (/p/, /reel/, /tv/) → snapinsta.ai via Playwright (headless, anúncios bloqueados, ~2 s/post)
→ links de download da mídia original (1080–1440 px) → bytes. Só FOTO (carrossel = todas as telas); vídeo é ignorado.
Sem links colados, `discover_posts` tenta achar posts do @ por busca (DuckDuckGo) — melhor esforço, pode vir vazio."""
from __future__ import annotations

import asyncio
import html as _html
import re
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote, unquote

import httpx

SNAP_URL = "https://snapinsta.ai/pt"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
_POST_RE = re.compile(r"instagram\.com/(?:[A-Za-z0-9._]+/)?(p|reel|tv)/([A-Za-z0-9_-]{5,})")
_BLOCK = ("googlesyndication", "doubleclick", "google-analytics", "googletagmanager", "adservice", "adsystem")


def normalize_post_urls(text: Any) -> List[str]:
    """Texto/lista com links → URLs canônicas únicas (na ordem)."""
    blob = " ".join(text) if isinstance(text, (list, tuple)) else str(text or "")
    out: List[str] = []
    for kind, code in _POST_RE.findall(unquote(blob)):
        u = f"https://www.instagram.com/{kind}/{code}/"
        if u not in out:
            out.append(u)
    return out


def post_code(url: str) -> str:
    m = _POST_RE.search(url or "")
    return m.group(2) if m else ""


def discover_posts(handle: str, name: str = "", limit: int = 24) -> List[str]:
    """Melhor esforço: posts do @ indexados na busca. Só aceita resultado cujo título/trecho cite o @ ou o nome."""
    handle = (handle or "").lstrip("@").strip().lower()
    if not handle:
        return []
    keys = {handle}
    if name and len(name.strip()) >= 4:
        keys.add(name.strip().lower())
    found: List[str] = []
    for q in (f"site:instagram.com/p {handle}", f"instagram.com/p \"{handle}\""):
        try:
            with httpx.Client(timeout=20, headers={"User-Agent": UA}) as c:
                r = c.get("https://html.duckduckgo.com/html/?q=" + quote(q))
            if r.status_code != 200:
                continue
            for block in r.text.split('class="result__body"')[1:]:
                text = _html.unescape(re.sub(r"<[^>]+>", " ", block)).lower()
                if not any(k in text for k in keys):
                    continue
                for u in normalize_post_urls(block):
                    if u not in found:
                        found.append(u)
        except Exception as exc:
            print(f"[snap] busca falhou: {str(exc)[:120]}", flush=True)
        if len(found) >= limit:
            break
    return found[:limit]


async def _links_for(pg, url: str, timeout_s: float = 45.0) -> List[Dict[str, str]]:
    await pg.goto(SNAP_URL, wait_until="domcontentloaded", timeout=60000)
    inp = pg.locator("input[name=url]").first
    await inp.fill(url)
    await inp.press("Enter")
    loops = int(timeout_s / 0.5)
    for _ in range(loops):
        await pg.wait_for_timeout(500)
        if await pg.locator("a[href*='rapidcdn.app/v2'], a[href*='cdninstagram.com']").count():
            break
        body = (await pg.inner_text("body"))[:1500].lower()
        if "error" in body and ("api" in body or "private" in body or "not found" in body):
            break
    await pg.wait_for_timeout(600)
    return await pg.eval_on_selector_all(
        "a[href*='rapidcdn.app/v2'], a[href*='cdninstagram.com']",
        "els=>els.map(e=>({label:(e.innerText||'').trim(), href:e.href}))")


VIEWER = "https://insta-stories-viewer.com/{h}/"
VIEWER_IMG = "https://cdn.iqsaved.com/img2.php?url="


async def profile_latest(handle: str, max_images: int = 10) -> Dict[str, Any]:
    """SÓ COM O @: abre o perfil público num visualizador anônimo (insta-stories-viewer) e baixa as imagens dos
    posts mais recentes (até 12, 1ª tela de cada carrossel, vídeo ignorado) em qualidade original (~1440 px).
    → {user:{...}, items:[{post_id, content}]} ."""
    import json as _json
    from urllib.parse import quote as _q
    from playwright.async_api import async_playwright
    handle = (handle or "").strip().lstrip("@").strip("/")
    frames: List[str] = []
    edges: List[Dict[str, Any]] = []
    user: Dict[str, Any] = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            pg = await browser.new_page(user_agent=UA)
            pg.on("websocket", lambda ws: ws.on(
                "framereceived", lambda d: frames.append(d if isinstance(d, str) else d.decode("utf8", "ignore"))))
            await pg.route("**/*", lambda r: r.abort() if (
                r.request.resource_type in ("image", "media", "font")
                or any(k in r.request.url for k in _BLOCK + ("yandex",))) else r.continue_())
            await pg.goto(VIEWER.format(h=handle), wait_until="domcontentloaded", timeout=45000)
            clicked = False
            for _ in range(70):                       # até ~35 s
                await pg.wait_for_timeout(500)
                for f in frames:
                    m = re.match(r"42(\[.*\])$", f, re.S)
                    if not m:
                        continue
                    try:
                        ev = _json.loads(m.group(1))
                        u = ((ev[1] or {}).get("data") or {}).get("user") or {}
                    except Exception:
                        continue
                    if u:
                        user = u
                    for e in (u.get("edges") or []):
                        if e.get("id") and all(x.get("id") != e.get("id") for x in edges):
                            edges.append(e)
                if edges:
                    break
                if user.get("is_private"):
                    break
                if user and not clicked:              # o feed de posts só vem ao abrir a aba "Publications"
                    try:
                        await pg.get_by_text("Publications", exact=True).first.click(timeout=3000)
                        clicked = True
                    except Exception:
                        pass
        finally:
            await browser.close()
    items: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=60, follow_redirects=True,
                                 headers={"User-Agent": UA, "Referer": "https://insta-stories-viewer.com/"}) as http:
        for e in edges:
            if len(items) >= max_images:
                break
            if str(e.get("is_video")).lower() == "true" or not e.get("display_url"):
                continue
            try:
                r = await http.get(VIEWER_IMG + _q(e["display_url"], safe=""))
                if r.status_code == 200 and len(r.content) > 5000:
                    items.append({"post_id": str(e.get("id")), "content": r.content,
                                  "file": e.get("display_url_filename") or ""})
            except Exception as exc:
                print(f"[snap] perfil {handle}: imagem falhou {str(exc)[:100]}", flush=True)
    print(f"[snap] perfil @{handle}: {len(edges)} posts vistos, {len(items)} imagens", flush=True)
    return {"user": {k: user.get(k) for k in ("username", "full_name", "is_private", "edges_count", "biography")},
            "items": items}


def _origin_url(href: str) -> str:
    """O link do snapinsta (rapidcdn) carrega no JWT a URL original do CDN do Instagram. O rapidcdn às vezes devolve
    o MESMO arquivo para telas diferentes do carrossel, então baixa-se direto da origem."""
    import base64
    import json
    try:
        tok = href.split("token=", 1)[1].split("&", 1)[0]
        part = tok.split(".")[1]
        part += "=" * (-len(part) % 4)
        return str(json.loads(base64.urlsafe_b64decode(part)).get("url") or "")
    except Exception:
        return ""


async def fetch_posts(urls: List[str], *, max_images: int = 24, per_post: int = 4,
                      progress: Optional[Callable[[Dict[str, Any]], None]] = None) -> List[Dict[str, Any]]:
    """→ [{post_url, index, content}] (só fotos). Um navegador para todos os posts, um por vez."""
    from playwright.async_api import async_playwright
    out: List[Dict[str, Any]] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            pg = await browser.new_page(locale="pt-BR", user_agent=UA)
            await pg.route("**/*", lambda r: r.abort() if (
                r.request.resource_type in ("image", "media", "font")
                or any(k in r.request.url for k in _BLOCK)) else r.continue_())
            async with httpx.AsyncClient(timeout=60, follow_redirects=True, headers={"User-Agent": UA}) as http:
                for n, url in enumerate(urls, 1):
                    if len(out) >= max_images:
                        break
                    got = 0
                    try:
                        links = await _links_for(pg, url)
                        photos = [l for l in links if "video" not in l["label"].lower()]
                        for i, l in enumerate(photos[:per_post]):
                            if len(out) >= max_images:
                                break
                            r = None
                            for src in (_origin_url(l["href"]), l["href"]):
                                if not src:
                                    continue
                                try:
                                    r = await http.get(src)
                                    if r.status_code == 200 and len(r.content) > 5000:
                                        break
                                except Exception:
                                    r = None
                            if r is not None and r.status_code == 200 and len(r.content) > 5000:
                                out.append({"post_url": url, "index": i, "content": r.content})
                                got += 1
                    except Exception as exc:
                        print(f"[snap] {url} falhou: {str(exc)[:160]}", flush=True)
                    print(f"[snap] {n}/{len(urls)} {url} → {got} foto(s)", flush=True)
                    if progress:
                        progress({"done": n, "total": len(urls), "images": len(out)})
                    await asyncio.sleep(0.8)
        finally:
            await browser.close()
    return out
