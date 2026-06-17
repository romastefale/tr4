# TR4 Music Only

Base musical limpa do TR4.

Mantido:

- comandos musicais públicos;
- provedores musicais internos;
- cards e extratos musicais;
- inline público musical;
- `/healthz` e `/readyz`;
- SQLite para dados musicais;
- rate limit simples em memória para comandos pesados.

A escolha de grupo existe apenas para publicar resultado musical onde o usuário e o bot estão presentes.


## Songcharts universal

Todos os usuários importados em `lastfm_profiles` entram automaticamente no ranking universal. O mosaico `/tnow` usa a união de `spotify_tokens` e `lastfm_profiles`.
