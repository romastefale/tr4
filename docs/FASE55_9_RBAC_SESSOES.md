# Fase 55.9 — RBAC runtime e sessões persistentes

Esta fase adiciona uma camada de delegação persistente no banco do Equalizador.

## O que muda

- As variáveis do Railway continuam sendo a base estável de autorização.
- O dono do código pode conceder ou revogar canais pelo Mini App, sem expor IDs na interface.
- As concessões runtime ficam em `eq_runtime_grants`.
- As sessões curtas do Equalizador deixam de depender apenas da memória do processo e passam a ser salvas em `eq_private_sessions`.

## Segurança

- Somente administrador principal pode conceder ou revogar canais runtime.
- A interface usa `usr_ref` e `grp_ref`, não IDs reais.
- O backend resolve as referências internamente.
- Direitos reais do bot continuam sendo verificados antes de executar ações.
- Erros continuam normalizados e sanitizados.

## Tabelas novas

- `eq_runtime_grants`
- `eq_private_sessions`

## Rotas novas

- `GET /equalizador/api/rbac/runtime`
- `POST /equalizador/api/rbac/runtime`
- `DELETE /equalizador/api/rbac/runtime/{grant_ref}`
- `POST /equalizador/api/sessoes/limpar-expiradas`

## Observação operacional

A camada runtime é aditiva. Ela não remove a necessidade de manter as variáveis principais corretas no Railway, especialmente `TR3_DATABASE_URL`, `TR4_EQUALIZADOR_MAESTRO_IDS`, `TR4_EQUALIZADOR_OPERADOR_IDS`, `TR4_EQUALIZADOR_PALCO_IDS` e `TR4_EQUALIZADOR_CANAIS`.
