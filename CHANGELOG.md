# Changelog

Todas as mudancas relevantes deste projeto devem ser registradas aqui e tambem no `CHANGELOG` interno em `app/ui/app.js` quando forem visiveis no app.

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
