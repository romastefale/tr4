# tigraoRADIO TR3

Bot de Telegram integrado ao Spotify e ao Last.fm para mostrar a música atual ou a última música ouvida, registrar reproduções, reactions nativas e rankings.

A UX principal foi mantida no mesmo padrão do TR2: `/playing`, gatilhos textuais, caption, contadores de plays/reactions nativas, `/myself` e `/songcharts`.

## Fontes de música

O bot usa uma camada unificada de música:

1. Se o usuário vinculou Last.fm com `/lastfm <username>`, o bot tenta ler o Last.fm primeiro.
2. Se não houver Last.fm válido, ou se a consulta falhar, o bot usa o Spotify conectado por `/login`.

## Comandos públicos

```text
/start
/help
/login
/logout
/lastfm <username>
/lastfmoff
/playing
/myself
/songcharts
```

## Gatilhos textuais

Também acionam a lógica de `/playing`:

```text
tocando, pifm, cyo, py, braya, dead, ag, rosan, roro, ro, rafarl, pipi, bressing, kur, xxt, ts, cebrutius, tigraofm, djpi, royalfm, geeksfm, radinho, qap
```

## Last.fm

Para conectar no privado ou em grupo:

```text
/lastfm username
```

Também aceita:

```text
/lastfm @username
```

Em grupo, o Last.fm é salvo para o usuário que enviou o comando, não para o grupo inteiro. Depois disso, `/playing` no grupo passa a usar o Last.fm daquele usuário, com Spotify como fallback.

Para remover, também no privado ou em grupo:

```text
/lastfmoff
```

O Last.fm usa scrobbles públicos via `user.getrecenttracks`. Não usa OAuth.

## Spotify

Para conectar:

```text
/login
```

O bot gera a URL OAuth do Spotify e salva `access_token`, `refresh_token` e expiração.

Para remover a sessão Spotify:

```text
/logout
```

## Variáveis de ambiente

A partir da Fase 1, os nomes canônicos usam prefixo `TR3_`. Os nomes antigos continuam aceitos como compatibilidade de migração.

```text
TR3_TELEGRAM_BOT_TOKEN
TR3_BASE_URL
TR3_ROOT_USER_ID
TR3_SPOTIFY_CLIENT_ID
TR3_SPOTIFY_CLIENT_SECRET
TR3_LASTFM_API_KEY
TR3_DATABASE_URL
TR3_DATA_DIR
TR3_TIGRAORESPONDE_TARGET_CHAT_ID
TR3_SECURITY_ALERT_CHAT_ID
TR3_AUDIT_LOG_CHAT_ID
TR3_MANAGED_GROUP_IDS
TR3_PANIC_MODE
TR3_PANIC_STOP_SERVER
TR3_SECURITY_MONITOR_ENABLED
TR3_SECURITY_MONITOR_INTERVAL_SECONDS
TR3_SECURITY_MONITOR_MAX_GROUPS
TR3_ANOMALY_WINDOW_SECONDS
TR3_ANOMALY_MAX_FORBIDDEN_WEBHOOKS
TR3_ANOMALY_MAX_PERMISSION_DENIED
TR3_SECURITY_ALERTS_ENABLED
TR3_SECURITY_AUDIT_VIEW_LIMIT
TR3_COMMAND_RATE_LIMIT_ENABLED
TR3_COMMAND_RATE_LIMIT_WINDOW_SECONDS
TR3_COMMAND_RATE_LIMIT_EXPENSIVE_PER_WINDOW
TR3_COMMAND_RATE_LIMIT_STANDARD_PER_WINDOW
```

Compatibilidade legado ainda aceita:

```text
TELEGRAM_BOT_TOKEN
BASE_URL
OWNER_ID
SPOTIFY_CLIENT_ID
SPOTIFY_CLIENT_SECRET
LASTFM_API_KEY
DATABASE_URL
DATA_DIR
```

`TR3_DATABASE_URL` é opcional. Se ausente, o projeto usa SQLite em `/data/app.db`.

O TR3 é SQLite-only nesta linha de evolução. Se `TR3_DATABASE_URL`/`DATABASE_URL` apontar para outro dialeto, o startup falha com erro explícito.

## Deploy Railway

O repositório contém `Procfile` e `railway.toml` com o mesmo start command:

```text
python -m app.bootstrap
```

Healthcheck:

```text
/healthz
```

Para usar no mesmo padrão do TR2, copie as variáveis do serviço TR2 no Railway e adicione `LASTFM_API_KEY`. Se usar o mesmo bot token, desligue/remova o webhook do TR2 antes de subir o TR3, porque um mesmo bot do Telegram só pode ter um webhook ativo por vez.

## Smoke test local

Antes do deploy, rode:

```text
python scripts/smoke_imports.py
```

O teste valida imports atuais, inicialização isolada do banco, parsers de moderação, aliases e limite de callback do Last.fm.

## Observações técnicas

- O Last.fm gera `track_id` curto no formato `lfm:<hash>` para caber em callbacks do Telegram.
- Likes em cards atuais usam reactions nativas do Telegram correlacionadas pela tabela `card_messages` e persistidas em `track_reactions`.
- `track_likes` existe como legado/migração; a fonte atual para reactions dos cards é `track_reactions`.
- A camada `music_service` evita misturar Last.fm dentro do serviço Spotify.
- As tabelas principais são `spotify_tokens`, `lastfm_profiles`, `track_plays`, `card_messages` e `track_reactions`.

## Phase 2 — grupos gerenciados e modo musical-only

A partir da Fase 2, `TR3_MANAGED_GROUP_IDS` define a allowlist inicial de grupos gerenciados para moderação/BTB/DDX. O bot ainda pode tocar música em grupos não gerenciados ou em grupos onde ele não é administrador, mas ações destrutivas e ferramentas de moderação exigem:

1. grupo presente em `managed_groups` e habilitado;
2. bot como administrador do grupo;
3. direito real compatível com a ação (`can_delete_messages`, `can_restrict_members`, `can_pin_messages`, `can_manage_tags`, etc.).

Grupos vistos pelo bot continuam sendo registrados em `tigrao_groups`, mas isso não concede permissão de moderação. Grupo conhecido e grupo gerenciado são conceitos diferentes.


## Phase 6 — segurança ativa

A partir da Fase 6, o TR3 possui uma camada inicial de segurança ativa:

- `task_registry` centraliza tasks de background com referência forte e log de exceções.
- `/healthz` passa a expor modo de segurança, status do monitor e contagem de tasks.
- `security_monitor` verifica periodicamente banco, webhook e direitos reais do bot em grupos gerenciados.
- `panic` mantém os modos `normal`, `alert`, `restricted` e `panic_stop`.

O modo `restricted` bloqueia ações destrutivas delegadas e automações destrutivas, mantendo o Owner operacional. `panic_stop` só deve parar o servidor se `TR3_PANIC_STOP_SERVER=true` estiver configurado explicitamente.

Variáveis principais da Fase 6:

```text
TR3_SECURITY_MONITOR_ENABLED=true
TR3_SECURITY_MONITOR_INTERVAL_SECONDS=300
TR3_SECURITY_MONITOR_MAX_GROUPS=50
TR3_ANOMALY_WINDOW_SECONDS=300
TR3_ANOMALY_MAX_FORBIDDEN_WEBHOOKS=5
TR3_ANOMALY_MAX_PERMISSION_DENIED=10
```

### Segurança ativa e rate limit

A partir da Fase 7, o painel privado inclui uma seção **Segurança** Owner-only para ver status, rodar check manual, alternar `normal`/`alert`/`restricted` e consultar audit log básico.

Alertas de segurança são best-effort e usam `TR3_SECURITY_ALERT_CHAT_ID` e `TR3_AUDIT_LOG_CHAT_ID`. Para desativar envio de alertas sem remover auditoria local, use:

```env
TR3_SECURITY_ALERTS_ENABLED=false
```

Comandos caros de música/cards recebem rate limit local por usuário+chat. Ajustes:

```env
TR3_COMMAND_RATE_LIMIT_ENABLED=true
TR3_COMMAND_RATE_LIMIT_WINDOW_SECONDS=60
TR3_COMMAND_RATE_LIMIT_EXPENSIVE_PER_WINDOW=6
TR3_COMMAND_RATE_LIMIT_STANDARD_PER_WINDOW=20
```


## Release candidate consolidado

Este pacote inclui a consolidação final após a Fase 10N. Consulte:

```text
TR3_RELEASE_CANDIDATE.md
TR3_FINAL_ENV_TEMPLATE.env
TR3_FINAL_VALIDATION_GUIDE.md
TR3_FINAL_ARCHITECTURE.md
```

Antes do deploy real, rode os testes em ambiente com dependências completas e valide `/healthz` e `/readyz`.
