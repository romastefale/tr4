# Fase 11 — Etapa 2 — `/show` owner inicial

Esta etapa cria a primeira entrada real do FSM owner/maestro:

- comando `/show` apenas na DM do owner;
- `show` listado apenas nos comandos privados do bot;
- governante comum não recebe acesso;
- grupos conhecidos são listados de forma sanitizada;
- diagnóstico tenta atualizar a afinação real do bot por grupo quando houver token;
- se a Bot API falhar, usa snapshot local/cache quando disponível;
- não expõe IDs técnicos no texto renderizado;
- não libera pacotes ainda;
- não altera Web App governante ainda.

## Fora desta etapa

- liberação de governantes;
- criação de pacotes no banco;
- DDX funcional;
- broadcast musical;
- postagem/foto;
- apagar/ban por link.

Esses itens ficam para as próximas etapas.
