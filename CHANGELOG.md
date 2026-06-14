# Changelog

Todas as mudancas relevantes deste projeto devem ser registradas aqui e tambem no `CHANGELOG` interno em `app/ui/app.js` quando forem visiveis no app.

## v1.19.11 - 2026-06-14

- Corrige o upload do MetaPorn OS quando o usuario seleciona um video sem sessao valida: o overlay de login agora e aguardado e o mesmo arquivo continua o envio apos autenticar, com uma nova tentativa quando a sessao expira durante o upload.

## v1.19.10 - 2026-06-13

- Ajusta a checagem inicial de autenticacao do MetaPorn OS para preservar a abertura visual anterior: respostas `missing_or_invalid_api_key` no boot apenas marcam auth pendente, e o login aparece quando uma acao protegida exige credencial.

## v1.19.9 - 2026-06-13

- Corrige a checagem de autenticacao do MetaPorn OS: respostas JSON `missing_or_invalid_api_key` passam a ser tratadas como bloqueio de auth mesmo quando o backend retorna HTTP 200, abrindo o login antes do upload.

## v1.19.8 - 2026-06-13

- Corrige a autenticacao do upload no MetaPorn OS: o XHR para `/uploads/local-stream` passa a reutilizar a `X-API-Key` salva na sessao da UI antiga, evitando `missing_or_invalid_api_key` quando o servidor exige API key.

## v1.19.7 - 2026-06-13

- Corrige o upload do MetaPorn OS apos a migracao para CariPost: a tela nova deixa de usar PUT direto no storage por presign e passa pelo endpoint backend `/uploads/local-stream`, com a mesma validacao de video da UI funcional.

## v1.19.6 - 2026-06-10

- Corrige o carregamento das capas no gerenciador Arquivos: as primeiras thumbnails da grade agora entram na fila imediatamente, sem depender de rolagem dentro da janela do MetaPorn OS.

## v1.19.5 - 2026-06-10

- Faz o login do MetaPorn OS respeitar `/auth/check`: quando a autenticacao esta ativa, o login aparece no desktop novo e a sessao e espelhada para os modulos antigos embutidos.

## v1.19.4 - 2026-06-10

- Restaura o funcionamento real dos módulos no MetaPorn OS: cada janela do desktop novo abre a rota funcional antiga em `/ui/?embed=1`, reaproveitando handlers, uploads, runs, Criacao, burn, teaser, settings e demais fluxos existentes.
- Mantem o visual do desktop MetaPorn OS e aumenta/centraliza os icones no topo da tela.
- Espelha a sessao do login do OS para a UI antiga, evitando login duplicado dentro das janelas.

## v1.18.21 - 2026-06-02

- Corrige a tela inicial para seguir o desktop do pacote Claude Designer: boot/login MetaPorn OS, grupos de apps completos e janela oculta quando nao ha rota direta.
- Mantem rotas, endpoints, loaders e funcoes tecnicas existentes; atalhos visuais de edicao apontam para a rota real de Criacao.

## v1.18.20 - 2026-06-02

- Corrige a entrega visual do Claude Designer com login em MetaPorn OS, desktop com apps agrupados, start menu, taskbar e janela principal.
- Preserva rotas, IDs, handlers, loaders, endpoints e fluxos tecnicos existentes.

## v1.18.19 - 2026-06-02

- Aplica a reestruturacao visual MetaPorn OS recebida no pacote `Metaporn.zip`.
- Transforma o shell atual em uma experiencia visual de desktop: launcher em blocos, janela principal em vidro escuro e barra inferior de atalhos.
- Preserva rotas, IDs, handlers e fluxos tecnicos existentes.

## v1.18.18 - 2026-05-25

- Corrige o burn de logo para manter a proporcao visual do preview e evitar logo achatada no video final.
- Adiciona exclusao de run/criacao com limpeza de registros relacionados, jobs e arquivos seguros.
- Atualiza o cache bust do painel admin para forcar carregamento da UI mais recente.

## v1.18.13 - 2026-05-22

- Versao anterior diagnosticada com ausencia de exclusao de run/criacao e problema de proporcao na logo durante burn.
