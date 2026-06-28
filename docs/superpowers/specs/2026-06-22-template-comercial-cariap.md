# Template comercial Cariap (compositor de post)

**Data:** 2026-06-22 · Problema: a IA gera só uma FOTO, não a peça comercial com
identidade (cores, logo embaixo, site, fale conosco). Layout escolhido pelo usuário:
**Hero no topo + rodapé de marca**. Usuário vai mandar prints reais da Cariap p/ fidelidade.

## Layout (1080×1350)
- Topo (~56%): arte IA (hero), cover-crop.
- Faixa do meio (cor primária da marca): TÍTULO/gancho + subtítulo + logo do app (canto).
- Rodapé (cor secundária/escura): logo Cariap (esq) + site + "Fale conosco" + @handle (dir).

## Fontes de dado (já temos)
- Cores: do produto (app) se houver, senão brand_kit da empresa (extraídas do logo).
- Logo Cariap: asset_list_logos(company). Logo app: asset_list_logos(company, product_id).
- site: company.website · handle: company.socials.instagram.
- título/subtítulo: do copy gerado.

## Implementação
- `app/services/template_composer.py` → `compose_branded_post(hero_bytes, title, subtitle,
  colors, company_logo_path, app_logo_path, site, handle)` → PNG (PIL, sem browser).
- `/generate-image`: gera hero → compõe template → salva. try/except: falha = usa hero puro.
- Lentidão: variações em paralelo (próximo) + modelo rápido por padrão.

## Pendente
- Prints reais da Cariap → ajustar cores exatas, fontes, posição de logo, proporção.
