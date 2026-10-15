# Identidade original: import pelo @, rodapé e tipografia (v1.27.159 → v1.27.163)

## Objetivo
Equiparar a arte gerada à arte original do cliente e tirar a "cara de IA" que sobrava:
- **tipografia:** a IA usava a sans geométrica genérica;
- **rodapé:** saía o rodapé genérico do Caripost, não o próprio da marca.

Tudo a partir só do @ do Instagram, sem login de ninguém.

## O que mudou

### 1. Artes do Instagram só com o @ (`app/services/insta_snap.py`)
- **`profile_latest(handle)`:** abre o perfil público em insta-stories-viewer.com (Playwright, anúncios bloqueados). Lê o feed pelo websocket, depois de clicar em "Publications", e baixa as imagens originais (cerca de 1440 px) pelo proxy cdn.iqsaved.com. Traz os 12 posts mais recentes; vídeo é ignorado.
- **`fetch_posts(urls)`:** links de posts específicos via snapinsta.ai. Baixa da URL original do CDN, que vem no JWT, porque o rapidcdn repetia o arquivo nas telas do carrossel.
- **`companies._ig_import`:** tenta primeiro a Meta oficial e, se não trouxer nada, usa o perfil público. O cadastro/enriquecimento importa **10 artes**.
- **`POST /companies/{id}/import-instagram-posts`:** roda como job com polling. Sem @ no corpo, usa o @ do cadastro.
- **Depois de importar** (`_refs_changed`): refaz DNA visual, rodapé e tipografia, exceto o que foi ajustado à mão.
- **Correção à parte:** o proxy da Composio usa `type` e não `in`. Isso quebrava a Business Discovery.

**Limites de outros caminhos testados:**
- o Instagram devolve 429 para o IP do servidor;
- buscadores bloqueiam a busca automática de posts;
- o Business Discovery não existe no login via Instagram (só via Facebook).

### 2. Rodapé original (`app/services/brand_footer.py`)
- **Detecção:** compara os "mapas de tinta" dos 28% de baixo de cada arte, tolerando deslocamento vertical. Rodapé que se repete em 2 ou mais artes é rodapé fixo (CARIAP: 2 de 8, semelhança 0,88).
- **Recorte:** fundo removido. Cada pixel recebe a cor de tinta real mais próxima (paleta das tintas), o que elimina halo e pontilhado. O recorte para no 1º vão vazio acima do fio.
- **`stamp`:** escolhe a versão (fundo claro/escuro) pela luminância do pé da arte. Sem versão escura, a tinta neutra inverte e a colorida fica igual. Debaixo do rodapé vai uma base opaca na cor do fundo, para nada da IA vazar.
- **Configuração:** `creative_config.design.footer_kit` (enabled, edited).

### 3. Tipografia original (`app/services/brand_fonts.py`)
- **Identificação automática:**
  - o OCR (tesseract) acha as palavras de título e de texto nas artes do padrão (as que têm o rodapé oficial), excluindo logos e nomes de produto;
  - cada fonte do Google Fonts escreve a mesma palavra e a comparação é feita glifo a glifo;
  - a visão só desempata.
- **Limitação real:** famílias geométricas parecidas (Inter, Exo 2, Rubik) ficam empatadas em cerca de 0,5%. Por isso existe o **ajuste manual** no cadastro, com prévia ao vivo, que fica travado contra a redetecção. A CARIAP está em **Exo 2 800 / 500**, conferido lado a lado.
- **Na geração (Estúdio IA, `reference_full`):**
  - o prompt diz a fonte;
  - vai a referência "AMOSTRA DA TIPOGRAFIA OFICIAL", com o título da tela já desenhado na fonte;
  - em seguida roda uma **2ª passada só de letreiro** (`reletter`, OmniRoute luna, custo ~0, cerca de 50s): refaz a arte idêntica trocando só o desenho das letras. Ela só é aceita se o OCR ler o texto tão bem quanto antes.

### 4. Tela (`apps-clientes.jsx`)
- **Cartão "Identidade original da marca":** prévia do rodapé (liga/desliga), fonte de títulos e texto com peso e prévia via Google Fonts, e o botão "Detectar de novo".
- **Importação:** só o campo @ e o botão "Importar artes do Instagram". Os links de posts específicos ficam em "opcional".

## Verificação
- CARIAP:
  - import por links trouxe 8 artes, todas da marca;
  - rodapé detectado nas 2 artes do padrão;
  - arte "Leitura no plano" regerada com Exo 2 e rodapé original, com o telefone certo (11 97445-1971; a arte anterior trazia o errado, 114210-1788);
  - letreiro com OCR de 0,94 para 1,00.
- Tanto: import só pelo @ pelo endpoint trouxe 8 imagens, 5 novas.
- `regressao_check.py` OK em todos os deploys.

## v1.27.164–165: o que o usuário reprovou e como foi resolvido
Na arte "Conexão atrai" o usuário apontou três problemas:
- o rodapé estava sem resolução, com cara de recorte;
- havia neon e excesso de luz, sem textura;
- a tipografia não era a da CARIAP.

Causas encontradas nos logs:
- a 2ª passada de letreiro foi RECUSADA pelo OCR (texto piorou de 0,83 para 0,72) e a fonte de IA ficou;
- as "artes de inspiração" eram aleatórias (quadrinhos/escuras);
- o rodapé era um recorte de 1080 px ampliado.

Correções:
1. **Rodapé reconstruído** (`brand_footer.extract_spec` + `render_spec`):
   - a geometria separa as caixas e a visão só classifica e transcreve cada uma (texto, ícone ou logo);
   - o rodapé é redesenhado na resolução da arte: logo OFICIAL (arquivo de 5660 px, versão escolhida pelas cores do original e com texto neutro invertido no fundo escuro), textos em Exo 2 com a mesma largura e o mesmo peso, fio vetorial na cor saturada da marca e ícone com borda nítida.
2. **Texto com a fonte real** (`app/services/retypeset.py`):
   - o OCR acha as linhas de título, texto e botão que a IA escreveu, casando com os textos esperados (inclusive texto branco em botão);
   - a IA apaga SÓ esses textos; se mexer no resto (diferença acima de 22) ou deixar palavras, o passo é abandonado;
   - a arte sobe para 2160 px e o Caripost escreve com o ARQUIVO da fonte, no mesmo lugar, na mesma cor e no mesmo alinhamento, com o texto do botão centralizado no botão;
   - se algo falhar, entra o plano B (passada de letreiro) e, em último caso, fica a arte da IA.
3. **Referências de acabamento:**
   - as artes do PADRÃO da marca (as que têm o rodapé oficial) entram como "ARTE ORIGINAL DA MARCA" com prioridade alta;
   - com rodapé original, só 1 logo da marca vai nas referências;
   - o prompt pede a textura sutil das originais e proíbe neon, glow e luzes, a não ser que as originais usem.

Teste: "Conexão atrai" regerada, com 4 referências (logo, amostra e 2 artes originais):
- limpeza com diferença de 2,5 fora do texto;
- título, texto e botão refeitos em Exo 2;
- fundo claro com textura geométrica e mapa do Brasil, sem neon;
- saída em 2160×2699.
