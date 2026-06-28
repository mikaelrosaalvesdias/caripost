#!/usr/bin/env python3
"""Teste de regressão GOLDEN do compositor de carrossel (rede de segurança da metodologia).

Renderiza um conjunto FIXO de slides (capa/conteúdo/CTA) com entradas FIXAS (logos sintéticas +
fotos sintéticas, zero IA, zero custo) e compara o hash de cada saída com a referência aprovada
em `golden.json`. Como o compositor é 100% determinístico, qualquer mudança de hash = mudança
real na arte. Assim a gente PROVA que uma alteração só mexeu no que devia.

Uso:
  python3 docs/marcos/regressao_check.py            # compara com golden.json (falha se mudou)
  python3 docs/marcos/regressao_check.py --update   # regrava golden.json (só após aprovação do marco)
"""
import sys, io, os, json, hashlib
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from PIL import Image, ImageDraw, ImageFont
from app.services.template_composer import compose_carousel_slide

HERE = os.path.dirname(__file__)
GOLDEN = os.path.join(HERE, "golden.json")
FONT = "/usr/share/fonts/truetype/brand/Poppins-Black.ttf"


def _logo(txt, color):
    im = Image.new("RGBA", (420, 130), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    try:
        f = ImageFont.truetype(FONT, 70)
    except Exception:
        f = ImageFont.load_default()
    d.text((10, 20), txt, font=f, fill=color)
    p = os.path.join(HERE, f"_golden_logo_{txt}.png")
    im.save(p)
    return p


def _photo(seed):
    im = Image.new("RGB", (1024, 1280)); px = im.load()
    for y in range(1280):
        for x in range(1024):
            px[x, y] = ((30 + seed * 7 + x % 30) % 255, (22 + y % 25) % 255, (42 + seed * 3) % 255)
    b = io.BytesIO(); im.save(b, "PNG"); return b.getvalue()


def render_suite():
    co = _logo("CARIAP", (237, 94, 31, 255))
    app = _logo("DEEZER", (150, 90, 255, 255))
    colors = {"accent": "#ED5E1F", "dark": "#141418", "bg": "#F2F2F0"}
    # (nome, idx, total, slide, logo_app, tem_foto). total FIXO por caso → adicionar casos novos
    # NÃO desloca os hashes dos antigos (idx/total não muda). tem_foto=False => fundo sólido (CTA laranja).
    suite = [
        ("capa",        1, 4, {"type": "cover", "eyebrow": "RETENCAO", "title": "Combo blinda a base", "subtitle": "linha"}, None, True),
        ("conteudo_1",  2, 4, {"type": "content", "title": "Filme musica e jogo no mesmo plano", "body": "Quando o plano junta tudo, o cliente para de comparar so o preco.", "number": 1}, None, True),
        ("conteudo_app", 3, 4, {"type": "content", "title": "Coloque Deezer na oferta", "body": "Musica que a familia usa todo dia vira motivo de ficar.", "number": 2, "app": "Deezer"}, app, True),
        ("cta",         4, 4, {"type": "cta", "title": "Aumente o ticket medio", "subtitle": "Fale com a CARIAP", "cta": "Fale conosco", "phone": "(11) 97445-1971"}, None, True),
        ("cta_laranja", 5, 5, {"type": "cta", "title": "Coloque Deezer na oferta", "subtitle": "Mais valor por assinante", "cta": "Fale conosco", "phone": "(11) 97445-1971"}, None, False),
    ]
    out = {}
    for name, idx, total, s, applogo, has_photo in suite:
        bg = _photo(idx) if has_photo else None
        png = compose_carousel_slide(s, idx, total, colors, co, "cariap.com.br", "cariap", bg, applogo, None)
        out[name] = hashlib.md5(png).hexdigest()
    return out


def main():
    cur = render_suite()
    update = "--update" in sys.argv
    if update or not os.path.exists(GOLDEN):
        json.dump(cur, open(GOLDEN, "w"), indent=2)
        print("golden.json", "ATUALIZADO" if update else "CRIADO", "->", cur)
        return 0
    ref = json.load(open(GOLDEN))
    diffs = [k for k in cur if ref.get(k) != cur[k]] + [k for k in ref if k not in cur]
    if diffs:
        print("REGRESSAO DETECTADA nas telas:", diffs)
        for k in diffs:
            print(f"  {k}: golden={ref.get(k)} != atual={cur.get(k)}")
        return 1
    print("OK — todas as", len(cur), "telas batem com o golden aprovado (nada quebrou).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
