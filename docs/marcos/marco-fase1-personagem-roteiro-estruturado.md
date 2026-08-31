# Marco Fase 1 — Personagem consistente + Roteiro estruturado + Editor por cena (v1.27.14)

Implementa os Estágios **B + C + D(parcial)** do `workflow-video-reestruturado.md`. No ar em
`caripost-new:1.27.14` (serviço `metaporn-new_adult-meta`, converged; `caripost.cariap.com.br/os/` em `?v=12714`).

## O que mudou tecnicamente

### B — Roteiro estruturado (JSON cinematográfico)
- `BRIEFING_GEN["video_storyboard_system"]` (ai.py) agora pede JSON com **`character`** (mapa do
  personagem) + por cena **`framing` / `movement` / `style`** além de `desc`/`seconds`.
- `build_video_storyboard` (ai.py) lê esses campos e compõe a cena com **linguagem de câmera**
  (Enquadramento/Movimento/Estilo). Cada `seconds` continua snapado em {4,8,12}.

### C — Personagem travado (acessório-âncora)
- O bloco `character.map` (idade+etnia+cabelo+rosto+pele+vestuário+**acessório-âncora único**) é gerado
  **1 vez** e **re-injetado em TODAS as cenas** via `char_clause` ("PERSONAGEM FIXO — a MESMA pessoa…").
- Cada cena retornada carrega `character_map` (o mesmo clause) p/ o preflight e o generate reusarem.
- Trava de produto: mantém o `_video_brief_context` (fatos reais do app) já existente.

### D(parcial) — Gate de aprovação por cena (custo ZERO até confirmar)
- `/video-preflight` agora devolve **`scene_descs`** (roteiro legível por cena) e **`character`**.
- `VideoCreator` (apps-conteudo.jsx) mostra um **editor por cena** (textarea editável) + selo
  **"🎭 Personagem travado"** + botão **"↻ Regerar roteiro"**.
- `/generate-branded-video` aceita `scene_descs` editados e **recompõe os prompts re-injetando o
  personagem** (`build_video_prompt(theme, character + desc_editada)`), preservando a consistência mesmo
  após edição. Sem edição → comportamento anterior (usa `storyboard` do preflight).

## Compatibilidade / segurança
- 100% backward-compatible: se a IA devolver o formato antigo (só `desc`/`seconds`), `char_clause`/cine
  ficam vazios → prompt idêntico ao de antes.
- **Não toca no motor de imagem** → `regressao_check.py` intacto. Sem novo provedor, sem custo novo.
- Tudo overridável por empresa via `creative_config.briefing` (templates do storyboard).

## Como testei (custo zero)
`py_compile` OK + **dry-run no container** (`caripost-new:1.27.14`) com `complete_ai` stubado: storyboard
de 15s →
- **2 cenas**; `character_map=True` nas duas;
- o **acessório-âncora ("brinco pequeno em formato de estrela") aparece nas DUAS cenas** (personagem travado);
- **close-up** aplicado na cena 2 (campos de câmera funcionando);
- `desc` fica **limpa** (sem a cláusula de personagem) → briefing legível.

## Como você testa (gera vídeo de verdade = gasta)
1. `caripost.cariap.com.br/os/` → Ctrl+Shift+R (pega o `?v=12714`).
2. Conteúdo → Briefing (Vídeo, trave 15s, gere o roteiro) → **Criação**.
3. Veja o **selo do personagem** + o **roteiro por cena editável**. Edite uma cena se quiser; "↻ Regerar
   roteiro" pra outra versão (sem custo — é só texto).
4. **Gerar vídeo** (confirma o custo) → no resultado, avalie **se é a MESMA pessoa nas 2 cenas** e se as
   cenas têm intenção de câmera.

**Avaliação pedida (só o que esta fase entrega):** mesma pessoa entre cenas + linguagem de câmera +
poder editar/regerar o roteiro antes de gastar. (Vision do produto, estilos virais e voz premium são
Fases 2–4, ainda não entram aqui.)
