# Collab (@) + Story simultâneo na publicação

**Versão:** v1.26.21

## Objetivo
Ao publicar o carrossel: (1) marcar o **@ do influencer** como **colaborador** do post; (2) postar a **capa como Story** ao mesmo tempo, **com opção** (toggle).

## O que mudou (técnico)

### Provider (`composio_provider.py`) — núcleo
- `_collaborators(post)`: lê `metadata.collaborators` (string ou lista), tira `@`, máx 3. **Testado** (string/lista/vazio/cap 3).
- Carrossel: o container `CAROUSEL` agora recebe `collaborators` quando há influencer.
- Post único: idem no container de imagem.
- `_maybe_publish_story(...)`: se `metadata.also_story`, cria container `media_type=STORIES` com a **capa** (re-host se preciso) e publica. **Falha no story NÃO derruba o feed** (feed já publicado) — só loga.

### Bridge (`service.py` create_post)
- `metadata.collaborators` ← `body.collaborators`; `metadata.also_story` ← `body.alsoStory`.

### Render (`posts.py`)
- O post do carrossel salva `meta.collab_handle` = @ do influencer usado (pra publicação marcar sozinho).

### UI (`apps-conteudo.jsx`, StepAgenda)
- Mostra **"🤝 Collab: @handle será marcado"** quando a arte usou influencer.
- Toggle por post **"Postar a capa como Story junto (simultâneo ao feed)"**.
- `doPublish` envia `collaborators` (do influencer) + `alsoStory` (do toggle).

## Provado por mim
- `py_compile` + `@babel/parser` (JSX OK).
- `_collaborators`: `'@joao'→['joao']`, `['@ana','bia']→['ana','bia']`, vazio→`[]`, 5→cap 3.
- Deploy v1.26.21 confirmado no ar.

## Honestidade (limites)
- **Não publiquei de verdade** (publicaria no seu IG real). O fluxo Composio (arg `collaborators` + `media_type=STORIES`) só se confirma 100% num post real — o **1º teste seu é a prova final**. Se a action do Composio não aceitar `collaborators`, o feed publica sem o collab e a gente loga (não quebra).
- O Story usa a **capa do carrossel (4:5)** → no story aparece com leve barra/recorte. Pra um Story **9:16 perfeito**, use o formato **Story** (que acabamos de criar) como arte dedicada.
