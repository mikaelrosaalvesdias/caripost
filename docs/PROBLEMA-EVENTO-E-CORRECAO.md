# Problema de divulgação de evento + correção técnica

## O PROBLEMA (relatado por você)

Pedi pra criar um post/carrossel **divulgando a participação da CARIAP no EXPO ISP Recife** (usar logos do evento, falar dos apps, mostrar datas). O que o app entregou:

1. **A "ideia" não virava instrução.** O sistema ignorou a intenção (divulgar evento) e jogou tudo no **mesmo molde institucional de apps** (E-Saúde, Deezer, ExitLag, um slide por app). Não tinha **nada sobre o evento**.
2. **Briefing sem o evento.** Não vinha data, não vinha local, não vinha nada do evento — mesmo com o evento cadastrado em Clientes → empresa do evento → evento.
3. **Logos do evento não apareciam** na arte.
4. **Influencer desconectado.** O cara da divulgação aparecia em fundo genérico, sem relação com o evento, e com expressão que não combinava (rosto triste num CTA de "visite o estande").
5. **Dados inventados.** Quando aparecia data/stand, eram **inventados pela IA** (ex.: "10 e 11 de novembro · estande 45"), não os do cadastro real (15–17/07, Recife, sem stand).
6. **Sem modularidade.** Só fazia um tipo de arte. Não dava pra escolher: institucional, evento, ou criativo livre (meme / data comemorativa).

Causa-raiz: o **gerador do briefing tinha um system prompt FIXO** ("carrossel de apps") e **forçava todo app a aparecer**; e o **prompt da imagem era fixo**, desligado do briefing. A inteligência (ideia → briefing → instrução de arte) não entendia a intenção nem usava o que estava cadastrado.

## O QUE FOI FEITO (técnico, no app)

| # | Correção | Onde (arquivo / função) |
|---|---|---|
| 1 | **Modos de intenção** no briefing: `produtos` / `evento` / `criativo`. O cérebro deixa de ser fixo em apps e passa a entender a intenção. | `app/services/ai.py` → `generate_carousel(..., intent, event)`, `generate_briefing(..., intent, event)` + 3 system prompts (`carousel_system`, `carousel_system_evento`, `carousel_system_criativo`) |
| 2 | **Não força app** fora do modo produtos (no evento os apps são a "oferta do estande"; no criativo são opcionais). | `ai.py` (`themed = [...] if intent=="produtos" else []`) |
| 3 | **Dado REAL do evento carimbado pelo código** no CTA (datas/local/stand do cadastro). A IA **não decide** datas. | `app/routers/posts.py` → `_format_event_info(ev)` + `slide_for_render["subtitle"] = event_cta_info` |
| 4 | **Regra anti-invenção** no prompt: proibido inventar datas/local/stand. | `ai.py` prompt `carousel_system_evento` |
| 5 | **Influencer compõe NA CENA do briefing** (não fundo genérico). | `posts.py` (pprompt usa `s["visual"]`) |
| 6 | **CTA desenha as datas** na arte (antes dropava o corpo). | `app/services/template_composer.py` (branch `cta` mostra `subtitle`) |
| 7 | **Logos do evento carimbadas** na capa/CTA. | `posts.py` (`event_logo_variants` → `slide_app_logos`) |
| 8 | **Campo Stand** no cadastro do evento + seletor de **modo** e de **evento** no Briefing. | `apps-clientes.jsx`, `apps-conteudo.jsx`, `db_companies.py`, `companies.py` |

Versão no ar: **v1.26.44**.

## STATUS DE VERIFICAÇÃO (honesto)

- **VERIFICADO (com você olhando):** a injeção de dado real. Rodado contra o SEU evento no banco: `EXPO ISP RECIFE · 15→17/07 · Recife, PE · sem stand` → o código carimba `"15 a 17 de julho de 2026 · Recife, PE"` (sem inventar stand).
- **VERIFICADO (texto):** os modos. Briefing em modo Evento fala do evento; modo Criativo (Brasil x Japão) faz newsjacking sem template de apps.
- **NÃO VERIFICADO:** o **carrossel renderizado inteiro** (capa+conteúdo+CTA com logos do evento + influencer na cena). Isso gera imagem (custo) e só prova de verdade gerando um carrossel real no modo Evento.
