"""Teste determinístico (sem IA) do saneamento de evento — planta novembro + stand 45 em TODOS os campos
(incluindo 'visual') e exige que NADA inventado sobreviva, e que CTA/capa tenham a data REAL.
Rodar dentro do container: python docs/marcos/test_event_sanitize.py"""
from app.services.ai import sanitize_event_plan

EV = {"date_start": "2026-07-15", "date_end": "2026-07-17", "location": "Recife, PE", "meta": {}}  # SEM stand
REAL = "15 a 17 de julho de 2026 · Recife, PE"

slides = [
    {"type": "cover", "title": "CARIAP na EXPO ISP, 10 e 11 de novembro",
     "visual": "influencer segurando placa stand 45 em novembro de 2026"},
    {"type": "content", "title": "Conheça os apps · suporte 24/7",
     "body": "Estaremos lá nos dias 10 e 11 de novembro · agenda 10/11", "visual": "estande #45 · 10/11/2026"},
    {"type": "cta", "title": "Visite o estande 45",
     "body": "Dias 10-11/11/2026, estande #45", "subtitle": "10/11/2026"},
]
sanitize_event_plan(EV, slides)

blob = " | ".join(str(s.get(f) or "") for s in slides for f in ("title", "body", "subtitle", "cta", "eyebrow", "visual"))
low = blob.lower()
has_november = "novembro" in low
has_stand45 = "45" in blob
has_numeric = ("10/11" in blob) or ("10-11" in blob) or ("11/2026" in blob)
keeps_247 = "24/7" in blob   # NÃO pode ser apagado (falso-positivo)
cta = [s for s in slides if s["type"] == "cta"][0]
cover = [s for s in slides if s["type"] == "cover"][0]
cta_ok = cta.get("body") == REAL and cta.get("subtitle") == REAL
cover_ok = cover.get("subtitle") == REAL

print("has_fake_november =", has_november)
print("has_stand_45      =", has_stand45)
print("has_numeric_10_11 =", has_numeric)
print("mantem 24/7 (nao falso-positivo)?", keeps_247)
print("cta body+subtitle = REAL?", cta_ok)
print("capa subtitle     = REAL?", cover_ok)
ok = (not has_november) and (not has_stand45) and (not has_numeric) and keeps_247 and cta_ok and cover_ok
print("\nRESULTADO:", "OK — nada inventado sobreviveu e 24/7 preservado" if ok else "FALHOU")
raise SystemExit(0 if ok else 1)
