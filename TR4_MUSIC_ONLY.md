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

Comandos públicos exibidos no menu:

- `/playing`;
- `/albnow`;
- `/tcanvas`;
- `/tstory`;
- `/tly`;
- `/radiofm`;
- `/tnow`;
- `/nowp`;
- `/myself`;
- `/weekfm`;
- `/monthfm`;
- `/songcharts`;
- `/lastfm`;
- `/lastfmoff`;
- `/login`;
- `/help`;
- `/start`.

Painéis antigos ou operacionais não devem aparecer no menu público. O startup regrava os escopos público, privado, grupos e administradores para evitar comandos antigos em clientes que preservam escopos anteriores.


## Fase 55.7 — Reações, auditoria e reactors

Adiciona janela Reações no Equalizador, auditoria sanitizada de `message_reaction`, seleção de reactors recentes e silêncio de reactor em modo conservador, sem expor ID real na interface.
