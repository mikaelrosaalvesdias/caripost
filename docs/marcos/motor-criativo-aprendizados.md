# Motor Criativo — Aprendizados (acertos/erros) → requisitos da FERRAMENTA

> Regra: a IA é NÃO-determinística. Cada geração é um sorteio. Uma FERRAMENTA não pode depender de sorte —
> tem que GARANTIR os acertos e BLOQUEAR os erros em TODA arte, com verificação + retry + partes de código
> consistentes. Este doc é a fonte da verdade do motor (não arte solta).

## ACERTOS a PRESERVAR (o que a final_1 acertou)
1. **Composição criativa pela IA** — cena + texto grande bem posicionado, mensagem em destaque (QUANDO dá certo).
2. **Identidade de marca** — paleta do brand kit injetada na instrução (ex.: CARIAP laranja #FF4F00).
3. **Logo carimbada pelo CÓDIGO** no topo — via `asset_list_logos(company_id)` + `compose_logos_only`. Posição ótima.
4. **Rodapé de contato pelo CÓDIGO** — `compose_cta_footer(site, phone)` com dados REAIS da empresa. (Usuário amou.)
5. **CTA** presente na arte.
6. **Modelo forte** — `kie:bytedance/seedream-v4-text-to-image` (o grátis fraco dava lixo).

## ERROS a BLOQUEAR (o que a final_2 errou)
1. **Texto sobre o sujeito** — "texto no meio do corpo do cara". A IA às vezes NÃO respeita o espaço negativo.
2. **Junk de marca desenhado pela IA** — logo falso "CARIP", escudo CBF, "Premium Instagram Presigns", hashtag, hex "#FF4350". A instrução (proibição) NÃO é 100% confiável.
3. **Rodapé com info inconsistente** — no teste eu variei site/phone por fallback do script. Na FERRAMENTA o rodapé tem que vir SEMPRE do registro da empresa (nunca hardcode/variação).

## REQUISITOS DA FERRAMENTA (garantias, não sorte)
1. **Gate de qualidade (visão) + retry** — após gerar, verificar por visão: (a) o texto NÃO cobre o rosto/sujeito; (b) NÃO há logo/marca/watermark/metadados desenhados pela IA. Se falhar → REGENERAR (teto N, ex.: 3), igual ao retry de rosto do influencer. Só publica arte que passa.
2. **Rede de segurança no topo (código)** — faixa/gradiente limpo no topo antes de carimbar a logo, para APAGAR qualquer junk residual (não depende da IA obedecer). Espelha o rodapé (que o usuário aprovou).
3. **Logo + rodapé SEMPRE por código, do registro da empresa** — nunca a IA. Dados de contato/site consistentes.
4. **Identidade por instrução** — paleta + DNA visual da empresa (configurável por `creative_config.design`), genérico p/ qualquer empresa.
5. **Não-repetitivo** — variação vem da cena/tema + seed; o gate garante que a variação nunca vira erro.
6. **Determinismo testável** — golden/fixtures com seed fixa; o gate roda em toda geração.

## VEREDITO DO USUÁRIO (2026-07-01, o mais importante)
Olhando a final_1: **"esse RODAPÉ é bom, o RESTO não presta."**
- O que o **CÓDIGO controla** (rodapé de contato, logo) = **BOM e confiável** (branded, consistente, sempre igual).
- O que a **IA gera solto** ("o resto": cena+título+layout) = **NÃO presta** (varia, junk, texto no sujeito, sorte).
- **Implicação de direção:** a régua é o RODAPÉ — elemento **desenhado por código, branded, bem projetado, 100% previsível**. Estender ESSA régua pro resto da arte: o código controla a composição (texto/hierarquia/marca) de forma **confiável e NÃO repetitiva** (o desafio é não repetir sem virar caixa engessada); a IA entra só como **fundo/foto/cena** (não desenha texto nem marca). = de volta ao caminho `photo_ai_composer` (IA faz a foto, código compõe), MAS com o código no nível de acabamento do rodapé — não a glass-box antiga.
- "IA arquiteta tudo" (legacy_ai_full_art) → **descartado** pelo usuário (não presta / não confiável).

## Próximo passo (implementação, não mais amostra solta)
Implementar o **gate de qualidade (visão) + retry** e a **rede de segurança do topo**; logo/rodapé já são código.
Assim a arte criativa fica confiável em TODA geração — a ferramenta garante o padrão da final_1, nunca o da final_2.
