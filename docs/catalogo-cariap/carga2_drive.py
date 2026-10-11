"""2ª carga CARIAP a partir das pastas do Drive (out/2026): logos oficiais, grade Zapping 2026,
adicionais atuais e documentos na base de conhecimento. Uso: python carga2_drive.py [--apply]"""
import json, os, sys, unicodedata, uuid, urllib.request, urllib.error

BASE = os.environ.get("CP_BASE", "http://127.0.0.1:8765")
CID = "e384c0d3-473b-46b0-8c10-ca5b753a09bd"
D = os.path.dirname(os.path.abspath(__file__))
L, DL = D + "/logos2/", D + "/dl/"
APPLY = "--apply" in sys.argv
TOKEN = None


def norm(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode().lower() if c.isalnum())


def call(method, path, body=None, fpath=None, ctype="application/octet-stream"):
    h = {"X-Session-Token": TOKEN} if TOKEN else {}
    data = None
    if fpath:
        b = uuid.uuid4().hex
        name = os.path.basename(fpath)
        data = (f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: {ctype}\r\n\r\n'.encode()
                + open(fpath, "rb").read() + f"\r\n--{b}--\r\n".encode())
        h["Content-Type"] = f"multipart/form-data; boundary={b}"
    elif body is not None:
        data = json.dumps(body).encode(); h["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        print(f"   !! HTTP {e.code} {method} {path}: {e.read()[:200]!r}")
        return {}


def act(desc, fn):
    print(("  ✔ " if APPLY else "  · ") + desc)
    return fn() if APPLY else None


def G(*names):
    return [n for n in names if os.path.exists(n) or print("   !! falta", n)]


LITE = ("SBT, Record, TV Brasil, RedeTV!, Gazeta, Zapping Mix, X Sports, Futura, Leo & Lully, Rede Brasil, Central TV, RFTV, "
        "PIX TV, Sesc TV, Play TV, Canal Gov, TV Justiça, TV Senado, Canal do Boi, Canal Solo Fértil, Agroplus, AgroCanal, "
        "TV Aparecida, TV Evangelizar, Canção Nova, Rede Gospel, Rede Mais Família, Rede CNT, Novo Tempo, Boa Vontade TV, RIT, "
        "Rede Vida, RS21, Daystar, LOF.AI e os canais Music (Urban Brasil, MPB, Hits, Soft Pop, Retrô, Classics, Rock, Sertanejo, Samba e Pagode)")
FULL_EXTRA = ("Esportes: Zapping Mix Esportes, ge tv, BandSports, N Sports, ESPN 1 a 6, SporTV 1, 2 e 3, Combate. "
              "Notícias: Zapping Mix News, GloboNews, CNN Brasil, Record News, BandNews, JP News, BM&C News, Fox News, BBC News, "
              "Times Brasil CNBC, CNN Money. Documentários e estilo de vida: Discovery Channel, Discovery ID, Discovery Turbo, "
              "Discovery Science, Discovery Theater, Discovery World, Animal Planet, TLC, H&H, Food Network, HGTV, Sabor & Arte, "
              "GNT, Modo Viagem, Canal Off, Arte1, Canal UOL, Multishow, Bis, Globoplay Novelas, New Brasil, TBC, Terraviva, C3 TV. "
              "Infantil: Gloob, Gloobinho, Discovery Kids, DumDum, Leo & Lully, Cartoonito, Cartoon Network. "
              "Filmes e séries: Megapix, Universal, USA, Studio Universal, Canal Brasil, AMC, Film & Arts, TCM, Space, Warner, "
              "TNT, TNT Series, TNT Novelas, Adult Swim. Internacionais: DW Español, Rai Italia, TV5Monde, NHK World Japan, "
              "France 24, RT, Arirang")

PLANS = {
    "zapping": {
        "Zapping Full": {
            "description": "Pacote Full: +120 canais ao vivo — todos os canais do Lite+ e mais esportes (ESPN, SporTV, Combate, ge tv), "
                           "notícias (GloboNews, CNN Brasil, BBC), filmes e séries (Megapix, Warner, TNT, Universal), Discovery e infantis. "
                           "Preço de referência B2C: R$ 89,90/mês (preço dinâmico da fornecedora).",
            "features": ["+120 canais ao vivo", "ESPN 1 a 6, SporTV 1-3, BandSports, Combate e ge tv", "GloboNews, CNN Brasil, BBC News, Fox News",
                         "Megapix, Warner, TNT, Universal, AMC, TCM", "Discovery, Animal Planet, GNT, Multishow", "Gloob, Discovery Kids, Cartoon Network",
                         "Aceita adicionais Telecine, Premiere e Canais Adultos"],
            "kb": "PACOTE FULL ZAPPING (+120 canais). Inclui todo o Lite+: " + LITE + ". Mais: " + FULL_EXTRA + "."},
        "Zapping Lite+": {
            "description": "Pacote Lite Plus: +45 canais ao vivo — canais abertos (SBT, Record, RedeTV!, Gazeta, TV Brasil), Zapping Mix, "
                           "X Sports, Futura, canais de fé, agro e os canais Music. Preço de referência B2C: R$ 19,90/mês (preço dinâmico da fornecedora).",
            "features": ["+45 canais ao vivo", "Abertos: SBT, Record, RedeTV!, Gazeta, TV Brasil", "Zapping Mix, X Sports, Futura, Leo & Lully",
                         "Canais de fé e agro", "9 canais Music (MPB, Sertanejo, Samba e Pagode...)", "Aceita adicionais Telecine, Premiere e Canais Adultos"],
            "kb": "PACOTE LITE PLUS ZAPPING (+45 canais): " + LITE + "."},
    },
    "ayabooks": {"Aya Books — Minibooks": {
        "description": "Minibooks: versões curtas de livros, com audiobook para ouvir no seu ritmo.",
        "features": ["Minibooks com audiobook", "Ouça no seu ritmo", "App Android e iOS"]}},
}

SOLUTIONS = {   # nome -> (descrição nova, logos novas, remover logos antigas?, kb)
    "Premiere": ("Adicional Zapping: inclui 8 canais Premiere — a maior cobertura do futebol nacional: Brasileirão Séries A e B, Copa do Brasil e principais estaduais.",
                 [L + "LOGOS_CANAIS_Adicionais_Premiere_premiere-color.png", L + "LOGOS_CANAIS_Adicionais_Premiere_premiere-white.png"], True,
                 DL + "LOGOS_CANAIS_Adicionais_Premiere_MANUAIS_PREMIERE_premiere_toolkit_02.pdf"),
    "Telecine": ("Adicional Zapping: inclui 6 canais Telecine — os canais das superestreias e das maiores bilheterias do cinema.",
                 [], False, DL + "LOGOS_CANAIS_Adicionais_Telecine_Manual_Telecine_e_Zapping_2023_.pdf"),
    "Canais Adultos": ("Adicional Zapping (+18): inclui Playboy TV, Venus, Sextreme e Sexy Hot.",
                       [L + n for n in ("LOGOS_CANAIS_Adicionais_Adultos_+18_PlayBoy_download.png", "LOGOS_CANAIS_Adicionais_Adultos_+18_Sextreme_Outros_formatos_sextreme-color.png",
                                        "LOGOS_CANAIS_Adicionais_Adultos_+18_Sexy_Hot_Outros_formatos_sexyhot-color.png", "LOGOS_CANAIS_Adicionais_Adultos_+18_Ve_nus_Outros_formatos_venus-white.png")], False, None),
}
REMOVE_SOLUTIONS = ["Combate", "Nosso Futebol+"]   # grade 2026: Combate já vem no Full; Nosso Futebol+ saiu dos adicionais

LOGOS = {
    "zapping": ["VA_2026_Logo_zapping_logotipo_dark.png", "A_2026_Logo_zapping_logotipo_white.png", "Logo_zapping_logotipo_zapink-pulse.png",
                "zapping_isotipo_zapink-pulse_alpha.png", "026_Iso_zapping_isotipo_dark_alpha.png", "26_Iso_zapping_isotipo_white_alpha.png"],
    "looke": [f"Looke_{i}.png" for i in range(1, 8)],
    "exitlag": ["itLag_Logos_ExitLag_Completo_Black.png", "g_Logos_ExitLag_Completo_FullWhite.png", "_Logos_ExitLag_Completo_Monochrome.png",
                "itLag_Logos_ExitLag_Completo_White.png", "itLag_Si_mbolo_Short-LogoFullBlack.png", "gos_ExitLag_Si_mbolo_ShortLogoDark.png",
                "ogos_ExitLag_Si_mbolo_ShortLogoRed.png", "os_ExitLag_Si_mbolo_ShortLogoWhite.png"],
    "deezer": ["Drive_Deezer_Logos_Deezer-Logo.png"],
    "ayabooks": ["_Drive_AYA_Books_Logos_AYA_E-books.png", "ive_AYA_Books_Logos_AYA_Audiobooks.png", "rive_AYA_Books_Logos_AYA_Minibooks.png"],
    "ayabancah": ["Drive_Bancah_Logo_Logo_Bancah.png"],
    "ayaensinah": ["ive_AYA_Ensinah_Logos_Logo_Ensinah.png", "inah_Logos_Logo_Ensinah_horizontal.png"],
    "exacloud": ["ive_EXA_Cloud_Logos_Logo_Exa_cloud.png"],
    "exagestaodigital": ["gital_Logo_EXA_Gestão_Digital_logo.png"],
    "exaseguranca": ["Logo_Exa_segurança_logo_horizontal.png", "Logo_EXA_Segurança_logo_branca.png", "Logo_Logo_exa_segurança_branco.png"],
}
KB = {
    "exitlag": ["3._Marca_ExitLag_Brandbook_ExitLag.pdf", "9._Suporte_+_FAQ_FAQ_Provedores_ExitLag.pdf", "9._Suporte_+_FAQ_2025_Suporte_Exitlag.pdf",
                "Cases_de_Sucesso.pdf", "7._Wiki_Gamer_Wiki_Gamer.pdf",
                "Plano_Gamer_com_ExitLag.pdf", "2._Trilha_de_Treinamentos_3._Tecnologia_Tecnologia_ExitLag.pdf"],
    "zapping": ["ARTES_Pacotes_Canais_PDF_ZAP_H_-_Pacotes", "MANUAIS_Celular_Tablet", "MANUAIS_Smart_TV", "MANUAIS_Reseller"],
    "esaude": ["Main_Branding_ESAU_DE.pdf"],
}
COLORS = {"zapping": {"primary": "#E90068", "secondary": "#0A0A0A", "accent": "#EF426F"}}


def find(dirpath, frag):
    hits = [f for f in os.listdir(dirpath) if f.endswith(frag) or frag in f]
    if not hits:
        print("   !! arquivo não encontrado:", frag)
    return dirpath + hits[0] if hits else None


def main():
    global TOKEN
    TOKEN = call("POST", "/auth/login", {"username": "mikaelrosaalvesdias@gmail.com", "password": os.environ["CP_PASS"]})["token"]
    prods = {norm(p["name"]): p for p in call("GET", f"/api/companies/{CID}/products")["products"]}
    for key, p in sorted(prods.items()):
        pid = p["id"]
        touched = any(key in d for d in (PLANS, LOGOS, KB, COLORS)) or key == "zapping"
        if not touched:
            continue
        print(p["name"])
        if key in COLORS:
            act("cores oficiais " + json.dumps(COLORS[key]), lambda: call("PUT", f"/api/companies/{CID}/products/{pid}", {"colors": COLORS[key]}))
        for fn in LOGOS.get(key, []):
            f = find(L, fn)
            if f:
                act("logo " + os.path.basename(f), lambda: call("POST", f"/api/companies/{CID}/products/{pid}/logo", fpath=f, ctype="image/png"))
        for fn in KB.get(key, []):
            f = find(DL, fn)
            if f:
                act(f"base ← {os.path.basename(f)} ({os.path.getsize(f)//1024} KB)", lambda: call(
                    "POST", f"/api/companies/{CID}/products/{pid}/kb", fpath=f if f.endswith(".pdf") else _as_pdf(f), ctype="application/pdf"))
        plans = {x["name"]: x for x in call("GET", f"/api/companies/{CID}/products/{pid}/plans").get("plans", [])}
        for name, spec in PLANS.get(key, {}).items():
            body = {k: spec[k] for k in ("description", "features")}
            if name in plans:
                plid = plans[name]["id"]
                act("atualiza plano " + name, lambda: call("PUT", f"/api/companies/{CID}/plans/{plid}", body))
            else:
                plid = (act("cria plano " + name, lambda: call("POST", f"/api/companies/{CID}/products/{pid}/plans",
                        {"name": name, **body, "colors": p.get("colors") or {}, "sort_order": len(plans)})) or {}).get("plan", {}).get("id")
            if spec.get("kb") and (plid or not APPLY):
                tmp = D + "/kb_" + norm(name) + ".txt"
                open(tmp, "w").write(spec["kb"])
                act("grade de canais → base do plano " + name, lambda: call("POST", f"/api/companies/{CID}/plans/{plid}/kb", fpath=tmp, ctype="text/plain"))
        if key == "zapping":
            sols = {x["name"]: x for x in call("GET", f"/api/companies/{CID}/products/{pid}/solutions").get("solutions", [])}
            for name in REMOVE_SOLUTIONS:
                if name in sols:
                    sid = sols[name]["id"]
                    act("remove adicional desatualizado " + name, lambda: call("DELETE", f"/api/companies/{CID}/solutions/{sid}"))
            for name, (desc, logos, drop_old, kb) in SOLUTIONS.items():
                s = sols.get(name)
                if not s:
                    print("   !! adicional não existe:", name); continue
                sid = s["id"]
                act("atualiza descrição " + name, lambda: call("PUT", f"/api/companies/{CID}/solutions/{sid}", {"description": desc}))
                if drop_old and logos:
                    for a in call("GET", f"/api/companies/{CID}/solutions/{sid}/assets").get("assets", []):
                        aid = a["id"]
                        act("  remove logo recortada antiga", lambda: call("DELETE", f"/api/companies/{CID}/solutions/{sid}/assets/{aid}"))
                for f in G(*logos):
                    act("  logo oficial " + os.path.basename(f), lambda: call("POST", f"/api/companies/{CID}/solutions/{sid}/logo", fpath=f, ctype="image/png"))
                if kb and os.path.exists(kb):
                    act(f"  base ← {os.path.basename(kb)}", lambda: call("POST", f"/api/companies/{CID}/solutions/{sid}/kb", fpath=kb, ctype="application/pdf"))


def _as_pdf(f):   # arquivos do Drive sem extensão (são PDFs)
    dst = f + ".pdf"
    if not os.path.exists(dst):
        os.link(f, dst) if hasattr(os, "link") else open(dst, "wb").write(open(f, "rb").read())
    return dst


if __name__ == "__main__":
    main()
