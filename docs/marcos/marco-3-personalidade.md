# Marco 3 — QUALIDADE via PERSONALIDADE (não padronice)

## Princípio (decidido pelo dono)
- A **QUALIDADE e a PERSONALIDADE vêm da INSTRUÇÃO** (prompt art-directed), não de template fixo.
- O **CÓDIGO = padronizador**: logo (variante por contraste), rodapé, texto com acento — tudo do Marco 0/1/2
  fica INTACTO. O motor NÃO é jogado fora; a personalidade é uma CAMADA por cima.
- Cada EMPRESA e cada PRODUTO tem sua **própria personalidade de design** (DNA de direção de arte). Capa
  padronizada (identidade), miolo com QUALIDADE e variação — nunca "tudo igual igual empresa de sorvete".
- Referência de qualidade: carrosséis do Lorenzi (roxo) / V4 / G4 — feitos por IA com prompt MUITO trabalhado.

## Personalidades por produto (DNA → tempera a instrução)
- **CARIAP (institucional):** moderno, futurista mas SÓBRIO/corporativo, confiável, tech, premium.
- **ExitLag (gaming):** futurista, velocidade, energia, neon, 3D, "bagunçado"/dinâmico, esportes, adrenalina.
- **Deezer (música):** futurista, música, ritmo, felicidade, dia a dia, cor, itens 3D, movimento.
- **E-Saúde (saúde):** mais tranquilo, institucional, cuidado, confiança, limpo, fala das dores do paciente.
- **Looke (filmes):** cinematográfico, imersivo, escapismo, dramático, "te tira da realidade".

## Arquitetura (estrutural, moldável — SaaS multi-empresa)
`creative_config.design.personality` por empresa + override por produto:
- Cada produto carrega um perfil: paleta/clima, palavras-chave de arte (neon/3D/cinemático/limpo), energia,
  tipo de cena, elementos. Esses tokens TEMPERAM o `_photo_only_prompt` (e o futuro prompt de design).
- A IA gera a IMAGEM com a personalidade do produto; o código carimba logo/rodapé/texto (confiável).
- Defaults bons embutidos (os 5 perfis acima) + editável por empresa/produto.

## A decidir com o dono (com evidência, não papo)
Texto: a IA desenha o slide INTEIRO (incl. texto) OU o código continua desenhando o texto?
- Teste feito (previews `_preview/aifull-*.png`): ver se a IA acerta texto/acento.
- Recomendação inicial: **personalidade/imagem pela IA + texto/logo pelo código** (confiável, sem acento quebrado),
  com o código VARIANDO posição por tela (mata a padronice). Decidir olhando o teste.

## Garantia
Antes/depois sempre com `regressao_check.py`; só mexo no motor com golden verde; backup por marco aprovado.
