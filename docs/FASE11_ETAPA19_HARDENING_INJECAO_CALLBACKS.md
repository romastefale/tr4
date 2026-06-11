# Fase 11 — Etapa 19 — Hardening de injeção e callbacks

## Objetivo

Endurecer os pontos finais de entrada do painel e do FSM owner contra HTML injection, URLs inseguras, callback forjado e payloads excessivos de diagnóstico.

## Correções

- `innerHTML` com nome de canal agora usa `escapeHtml`.
- Mensagem do diagnóstico público agora escapa título e texto antes de entrar em `innerHTML`.
- Player público passa a validar URLs com `safeUrl`, aceitando apenas `http://` ou `https://` em links/capas/fotos de grupo renderizadas em atributos HTML.
- `/equalizador/api/client-error` ignora payload acima de 4096 bytes e neutraliza sinais `<` e `>` antes de logar.
- `/show` ganhou allowlist de `callback_data`.
- `/show` não grava grupo/governante no state se a referência do callback não existir mais.
- Exceção 24h só pode ser cancelada se existir no assignment selecionado.
- Palavra/frase DDX digitada no FSM agora é limitada antes da persistência e recusa sinais de HTML.

## Fora do escopo

- Não muda deploy.
- Não altera permissões dos pacotes.
- Não altera Bot API.
- Não altera a UX visual além da sanitização de dados.
