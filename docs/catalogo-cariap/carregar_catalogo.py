"""Carrega o catálogo CARIAP (catalogo_cariap.json) no Caripost via API.
Idempotente: só cria o que falta (produto/plano/à la carte por nome); produtos existentes
mantêm logo/base/cores. Uso: python carregar_catalogo.py [--apply]"""
import json, os, sys, unicodedata, uuid, urllib.request, urllib.error

BASE = os.environ.get("CP_BASE", "https://caripost.cariap.com.br")
CID = "e384c0d3-473b-46b0-8c10-ca5b753a09bd"   # CARIAP
HERE = os.path.dirname(os.path.abspath(__file__))
LOGOS = os.environ.get("CP_LOGOS", "/opt/links/docs/apps/logos")
APPLY = "--apply" in sys.argv
TOKEN = None


def norm(s):
    s = unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode().lower()
    return "".join(ch for ch in s if ch.isalnum())


def call(method, path, body=None, files=None):
    headers = {"X-Session-Token": TOKEN} if TOKEN else {}
    data = None
    if files:
        b = uuid.uuid4().hex
        parts = []
        for field, (fname, content, ctype) in files.items():
            parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{field}"; filename="{fname}"\r\n'
                         f'Content-Type: {ctype}\r\n\r\n'.encode() + content + b"\r\n")
        data = b"".join(parts) + f"--{b}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={b}"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} {method} {path}: {e.read()[:300]!r}")


def act(desc, fn):
    print(("  ✔ " if APPLY else "  · ") + desc)
    return fn() if APPLY else None


def main():
    global TOKEN
    TOKEN = call("POST", "/auth/login", {"username": "mikaelrosaalvesdias@gmail.com", "password": os.environ["CP_PASS"]})["token"]
    spec = json.load(open(os.path.join(HERE, "catalogo_cariap.json")))
    existing = {norm(p["name"]): p for p in call("GET", f"/api/companies/{CID}/products")["products"]}
    for sp in spec["produtos"]:
        prod = existing.get(norm(sp["name"]))
        print(("EXISTE " if prod else "NOVO   ") + sp["name"])
        if not prod:
            payload = {k: sp[k] for k in ("name", "category", "colors", "description", "objective", "functions") if k in sp}
            prod = act("cria produto", lambda: call("POST", f"/api/companies/{CID}/products", payload)["product"])
            if sp.get("logo"):
                act("logo " + sp["logo"] + ".png", lambda: call("POST", f"/api/companies/{CID}/products/{prod['id']}/logo",
                    files={"file": (sp["logo"] + ".png", open(f"{LOGOS}/{sp['logo']}.png", "rb").read(), "image/png")}))
            if sp.get("kb"):
                txt = open(os.path.join(HERE, "pdftxt", sp["kb"] + ".txt"), "rb").read()
                act(f"base de conhecimento ({len(txt)} bytes da apresentação)", lambda: call(
                    "POST", f"/api/companies/{CID}/products/{prod['id']}/kb",
                    files={"file": (f"apresentacao-{sp['kb']}.txt", txt, "text/plain")}))
        pid = (prod or {}).get("id")
        have_plans = {norm(x["name"]) for x in (call("GET", f"/api/companies/{CID}/products/{pid}/plans").get("plans", []) if pid else [])}
        for i, pl in enumerate(sp.get("plans", [])):
            if norm(pl["name"]) in have_plans:
                print("  = plano já existe: " + pl["name"]); continue
            body = {"name": pl["name"], "description": pl["description"], "features": pl.get("features", []),
                    "colors": pl.get("colors") or sp.get("colors") or (prod or {}).get("colors") or {}, "sort_order": i}
            act("plano " + pl["name"], lambda: call("POST", f"/api/companies/{CID}/products/{pid}/plans", body))
        have_sols = {norm(x["name"]) for x in (call("GET", f"/api/companies/{CID}/products/{pid}/solutions").get("solutions", []) if pid else [])}
        for so in sp.get("solutions", []):
            if norm(so["name"]) in have_sols:
                print("  = à la carte já existe: " + so["name"]); continue
            body = {"name": so["name"], "description": so["description"], "colors": so.get("colors", {}), "category": "Conteúdo adicional"}
            sol = act("à la carte " + so["name"], lambda: call("POST", f"/api/companies/{CID}/products/{pid}/solutions", body)["solution"])
            if so.get("logo"):
                act("  logo " + so["logo"], lambda: call("POST", f"/api/companies/{CID}/solutions/{sol['id']}/logo",
                    files={"file": (os.path.basename(so["logo"]), open(os.path.join(HERE, so["logo"]), "rb").read(), "image/png")}))


if __name__ == "__main__":
    main()
