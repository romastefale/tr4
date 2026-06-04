# TR3 — Mapa final de arquitetura operacional

## Entradas principais

- `/tigrao`: entrada modular privada.
- `/owner`: painel Owner.
- `/radio`: painel Radio.
- `/healthz`: liveness.
- `/readyz`: readiness.

## Separação de responsabilidades

### Owner

- Governança estrutural.
- Segurança/panic mode.
- Moderadores/grants.
- Auditoria/exportação.
- Diagnóstico de direitos do bot.

### Delegados de moderação

- Ações concedidas por grupo em `moderation_grants`.
- Sem governança estrutural.

### Delegados Radio

- Ações `radio.*` concedidas por grupo.
- Sem `/owner`.

### Grupos sem admin

- Operação musical-only.
- Ações administrativas sinalizadas como indisponíveis.

## Persistência SQLite

Inclui tabelas para:

- grants/permissões;
- auditoria;
- grupos gerenciados;
- drafts/templates/histórico Radio;
- agendamentos e políticas Radio;
- sessões privadas;
- locks operacionais;
- operações críticas;
- status de direitos reais do bot.

## Segurança operacional

- RBAC por grupo.
- ContextVar por usuário com reset no final do webhook.
- Locks SQLite para tarefas críticas.
- Auditoria de intenção/resultado.
- Export com manifesto/hash.
- Export criptografado opcional com rotação via `key_id`.
