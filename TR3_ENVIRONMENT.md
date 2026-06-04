# TR3 — Variáveis de ambiente recomendadas para deploy

Este arquivo consolida as variáveis canônicas `TR3_*` após as fases de correção e segurança.

## Obrigatórias

```text
TR3_TELEGRAM_BOT_TOKEN=<token do bot>
TR3_BASE_URL=https://<seu-deploy>
TR3_ROOT_USER_ID=<seu Telegram user_id>
TR3_DATABASE_URL=sqlite:////data/app.db
```

## Spotify

```text
TR3_SPOTIFY_CLIENT_ID=<client id>
TR3_SPOTIFY_CLIENT_SECRET=<client secret>
TR3_SPOTIFY_REDIRECT_URI=https://<seu-deploy>/callback
```

## Last.fm

```text
TR3_LASTFM_API_KEY=<api key>
```

## Grupos gerenciados

Apenas grupos nesta lista aceitam moderação/BTB/DDX. Em grupos sem admin, o bot opera apenas como musical.

```text
TR3_MANAGED_GROUP_IDS=-1001234567890,-1009876543210
```

## Segurança e auditoria

```text
TR3_SECURITY_ALERT_CHAT_ID=<chat_id para alertas ou seu user_id>
TR3_AUDIT_LOG_CHAT_ID=<chat_id opcional para auditoria>
TR3_SECURITY_ALERTS_ENABLED=true
TR3_SECURITY_MONITOR_ENABLED=true
TR3_SECURITY_MONITOR_INTERVAL_SECONDS=300
TR3_SECURITY_MONITOR_MAX_GROUPS=50
```

## Panic/restricted mode

```text
TR3_PANIC_MODE=normal
TR3_PANIC_STOP_SERVER=false
TR3_ANOMALY_WINDOW_SECONDS=300
TR3_ANOMALY_MAX_FORBIDDEN_WEBHOOKS=5
TR3_ANOMALY_MAX_PERMISSION_DENIED=10
```

## Rate limit

```text
TR3_COMMAND_RATE_LIMIT_ENABLED=true
TR3_COMMAND_RATE_LIMIT_WINDOW_SECONDS=60
TR3_COMMAND_RATE_LIMIT_EXPENSIVE_PER_WINDOW=3
TR3_COMMAND_RATE_LIMIT_STANDARD_PER_WINDOW=10
```

## Delegação inicial opcional

Use apenas se quiser bootstrap de moderadores legados nos grupos de `TR3_MANAGED_GROUP_IDS`. Eles recebem permissões de moderação, não governança estrutural.

```text
TR3_SECOND_MODERATOR_ID=<telegram user_id>
TR3_THIRD_MODERATOR_ID=<telegram user_id>
```

## Tigraoresponde

```text
TR3_TIGRAORESPONDE_TARGET_CHAT_ID=<chat_id alvo>
```

## Regras operacionais

- SQLite é o banco oficial nesta versão.
- `TR3_DATABASE_URL` não-SQLite deve falhar no startup.
- Governança estrutural do grupo é Owner-only.
- Moderadores delegados só recebem permissões de moderação por grupo.
- Sem admin no grupo, o bot atua apenas como musical.
- `TR3_PANIC_STOP_SERVER=true` deve ser usado só se você aceitar parada extrema do servidor.


## Radio — agendamento

```text
TR3_RADIO_SCHEDULER_ENABLED=true
TR3_RADIO_SCHEDULER_INTERVAL_SECONDS=60
TR3_RADIO_SCHEDULER_MAX_DUE_PER_TICK=10
```

Regras:

- Agendamento usa templates de texto.
- Broadcast usa templates e respeita janela de silêncio.
- Envio duplicado recente é bloqueado por hash por grupo.
- Radio continua Owner-only até criação de permissões `radio.*`.


## Radio — permissões delegáveis

Permissões `radio.*` são concedidas por grupo, no mesmo painel de Moderadores:

```text
radio.view
radio.post_text
radio.post_media
radio.pin
radio.templates.use
radio.templates.manage
radio.history.read
radio.schedule
radio.quiet_hours.manage
radio.broadcast
```

Pacotes aceitos no painel:

```text
user_id *:mod
user_id *:radio
user_id *:all
```

Regra: `radio.broadcast` de usuário delegado só envia para grupos onde esse usuário também possui `radio.broadcast`.


## Radio — Fase 9G

A interface do `/radio` agora filtra botões conforme permissões `radio.*` no grupo selecionado.

Callbacks sensíveis de templates/páginas usam parser central em `app/security/callbacks.py`.

Listas de templates, histórico e agendamentos possuem paginação básica via callbacks:

```text
radio:templates:page:<n>
radio:history:page:<n>
radio:schedules:page:<n>
```


## Operação — Fase 10A

Endpoints:

```text
/healthz  -> processo vivo
/readyz   -> pronto para receber tráfego
```

`/readyz` retorna 503 se banco, token, dispatcher ou inicialização essencial não estiverem prontos.


## Comandos por escopo — Fase 10B

O menu nativo `/` do Telegram é configurado por escopo:

```text
default/all_groups -> comandos públicos musicais
Owner privado      -> /tigrao, /owner, /radio, /btb + públicos
Delegado legado    -> /tigrao, /radio + públicos
```

Comandos sensíveis não entram no escopo público. Delegados dinâmicos `radio.*` continuam autorizados pelo RBAC em runtime; o menu nativo deles só é atualizado automaticamente quando o user_id é conhecido em variáveis legadas.


## Comandos dinâmicos — Fase 10C

Quando o Owner concede ou revoga permissões pelo painel Moderadores, o bot tenta sincronizar o menu nativo privado do usuário afetado.

Regras:

```text
Owner             -> /tigrao, /owner, /radio, /btb + públicos
Usuário só com grant de moderação -> /tigrao + públicos
Usuário com grant radio.*       -> /tigrao, /radio + públicos
Usuário sem grant               -> comandos públicos
```

Falha de sincronização do menu não reverte o grant/revoke. Segurança real continua no RBAC.


## Resync administrativo de comandos — Fase 10D

O painel Segurança possui um botão Owner-only para ressincronizar menus nativos de usuários com grants ativos.

```text
Segurança -> Ressincronizar menus
```

O resync inclui:

```text
Owner
moderadores legados por env
usuários com grants ativos no banco
```

Falhas de menu não alteram permissões. A autorização real continua no RBAC.


## Direitos reais do bot nos botões — Fase 10E

O painel usa o cache/status de direitos reais do bot para sinalizar ações impossíveis no grupo selecionado.

Capacidades usadas:

```text
delete       -> can_delete_messages
restrict     -> can_restrict_members
pin          -> can_pin_messages
tags         -> can_manage_tags
change_info  -> can_change_info
invite       -> can_invite_users
topics       -> can_manage_topics
```

Quando uma capacidade falta, o botão aparece como `Indisponível: ...` e explica qual direito Telegram está ausente.

A checagem dura de segurança continua nos handlers antes da chamada Telegram.


## Diagnóstico de direitos do bot — Fase 10F

O painel Segurança possui ações Owner-only para atualizar e diagnosticar direitos reais do bot:

```text
Atualizar direitos do grupo
Diagnóstico direitos todos
```

O refresh consulta Telegram, atualiza o cache/status em `managed_group_status` e mostra capacidades reais:

```text
can_delete_messages
can_restrict_members
can_pin_messages
can_change_info
can_invite_users
```

Nenhuma permissão interna é concedida ou revogada por esse diagnóstico.


## Hardening de sessão privada — Fase 10G

O contexto de usuário dos painéis privados agora usa token/reset explícito em `finally` no webhook. Isso reduz risco de vazamento de `ContextVar` entre updates.

O painel Segurança possui ações Owner-only:

```text
Diagnóstico sessões
Limpar sessões expiradas
```

O diagnóstico mostra metadados e chaves de payload, mas não valores de payload sensíveis.

## Sessões persistentes e locks operacionais — Fase 10H

Novas variáveis:

```text
TR3_SESSION_PERSISTENCE_ENABLED=true
TR3_OPERATIONAL_LOCK_TTL_SECONDS=90
```

A Fase 10H adiciona persistência leve em SQLite para sessões privadas e locks operacionais:

```text
private_sessions
operational_locks
```

Objetivo:

- recuperar estado de painel após reinício curto;
- reduzir colisão entre múltiplas réplicas/processos;
- evitar duplo processamento do scheduler do Radio.

O lock atual aplicado em runtime é:

```text
radio_scheduler
```

O painel Segurança ganhou diagnósticos de sessões persistidas e locks operacionais. Nenhum lock ou sessão concede permissão; RBAC continua sendo a autoridade.


## Locks por ação crítica — Fase 10I

Ações críticas passam a usar locks SQLite em `operational_locks`:

```text
radio_broadcast
security_mode
governance:<chat_id>:<action>
```

Objetivo: evitar execução concorrente em múltiplos processos/réplicas para broadcast, panic/security mode e governança estrutural. Falha de lock bloqueia a ação, mas não altera permissões internas.


## Auditoria de operações críticas — Fase 10J

Operações críticas agora registram intenção e resultado em SQLite:

```text
critical_operations
```

Cobertura inicial:

```text
Radio broadcast
Security mode / panic mode manual
Governança estrutural
```

O pacote de replay é apenas informativo/manual. Nenhum replay automático é executado.


## Retenção/exportação de auditoria — Fase 10K

Variáveis:

```text
TR3_AUDIT_EXPORT_LIMIT=1000
TR3_AUDIT_RETENTION_DAYS=90
TR3_CRITICAL_OPERATION_EXPORT_LIMIT=1000
TR3_CRITICAL_OPERATION_RETENTION_DAYS=180
```

O painel Segurança possui export Owner-only para `audit_events` e `critical_operations` em JSONL. A limpeza antiga exige confirmação e não altera grants/RBAC.


## Export assinado e compactado — Fase 10L

O painel Segurança possui exports Owner-only compactados e assinados por SHA-256:

```text
Exportar auditoria .gz
Exportar operações .gz
```

Cada export envia dois arquivos:

```text
*.jsonl.gz
*.jsonl.gz.manifest.json
```

O manifesto contém:

```text
record_count
raw_size_bytes
gzip_size_bytes
raw_sha256
gzip_sha256
source
created_at
```

A assinatura é hash SHA-256 para verificação de integridade; não é assinatura criptográfica com chave privada.


## Backup criptografado opcional — Fase 10M

Exports de auditoria podem ser criptografados localmente antes do envio no privado do Owner.

Variável:

```text
TR3_AUDIT_EXPORT_ENCRYPTION_KEY=...
```

Formatos aceitos:

```text
passphrase textual
base64:<32 bytes em base64>
b64:<32 bytes em base64>
```

Quando a chave é passphrase, o código usa PBKDF2-HMAC-SHA256 com salt aleatório e AES-256-GCM. Quando a chave é `base64:`, ela precisa decodificar para 32 bytes e é usada como chave AES-256 direta.

Arquivos gerados:

```text
*.jsonl.gz.enc
*.jsonl.gz.enc.manifest.json
```

O manifesto registra algoritmo, nonce, KDF, hashes SHA-256 e metadados. A chave nunca é gravada no manifesto.


## Rotação de chaves de export criptografado — Fase 10N

Variáveis novas:

```text
TR3_AUDIT_EXPORT_ENCRYPTION_KEY_ID=current
TR3_AUDIT_EXPORT_DECRYPTION_KEYS=old-2026-05=passphrase-antiga;old-2026-04=base64:<32 bytes>
```

Regras:

- `TR3_AUDIT_EXPORT_ENCRYPTION_KEY` é a chave atual usada para novos exports.
- `TR3_AUDIT_EXPORT_ENCRYPTION_KEY_ID` é gravado no manifesto dos novos exports.
- `TR3_AUDIT_EXPORT_DECRYPTION_KEYS` guarda chaves antigas apenas para decrypt offline/recuperação manual.
- O manifesto grava `key_id`, mas nunca grava a chave.

Checklist de rotação segura:

1. Defina nova `TR3_AUDIT_EXPORT_ENCRYPTION_KEY`.
2. Atualize `TR3_AUDIT_EXPORT_ENCRYPTION_KEY_ID`.
3. Mova a chave anterior para `TR3_AUDIT_EXPORT_DECRYPTION_KEYS`.
4. Gere um export criptografado de teste.
5. Valide decrypt offline usando o manifesto e o keyring.
6. Só depois remova chaves antigas que não precisam mais descriptografar backups históricos.
