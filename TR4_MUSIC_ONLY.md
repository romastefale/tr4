# TR4 Music Only

Esta variante remove/desativa os painéis e fluxos de moderação, governança, panic mode, auditoria crítica e BTB.

Mantido:

- comandos musicais públicos;
- Last.fm/Spotify;
- cards e extratos musicais;
- inline público musical;
- `/healthz` e `/readyz`;
- SQLite para dados musicais;
- rate limit simples em memória para comandos pesados.

Removido/desativado:

- `/tigrao`;
- `/owner`;
- `/radio` de governança/postagem administrativa;
- moderação por grupo;
- panic/security mode;
- BTB;
- exports/auditoria crítica;
- locks operacionais de moderação.


## Fase 55.7 — Reações, auditoria e reactors

Adiciona janela Reações no Equalizador, auditoria sanitizada de `message_reaction`, seleção de reactors recentes e silêncio de reactor em modo conservador, sem expor ID real na interface.
