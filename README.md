# TR4 Music Only

Bot Telegram com foco apenas musical.

## Start command

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Railway SQLite

Use volume em `/app/data` e variável:

```text
TR3_DATABASE_URL=sqlite:////app/data/app.db
```

## Equalizador Mini App — fase 8

O Equalizador é registrado somente quando `TR4_EQUALIZADOR_ENABLED=true`.
Com o valor padrão `false`, a rota `/equalizador` não é incluída no app e o bot continua sem comando, botão ou menu público para essa área.

Variáveis mínimas da fase 8:

```text
TR4_EQUALIZADOR_ENABLED=false
TR4_EQUALIZADOR_APP_NAME=equalizador
TR4_EQUALIZADOR_MAESTRO_IDS=
TR4_EQUALIZADOR_OPERADOR_IDS=
TR4_EQUALIZADOR_PALCO_IDS=
TR4_EQUALIZADOR_CANAIS=
TR4_EQUALIZADOR_HIDE_TECHNICAL_IDS=true
TR4_EQUALIZADOR_INITDATA_MAX_AGE_SECONDS=600
TR4_EQUALIZADOR_SESSION_TTL_SECONDS=28800
TR4_EQUALIZADOR_RATE_LIMIT_PER_MINUTE=120
```

As APIs `/equalizador/api/me`, `/equalizador/api/palcos`, `/equalizador/api/canais` e `/equalizador/api/palcos/{grp_ref}/afinacao` exigem `Authorization: tma <Telegram.WebApp.initData>` ou sessão curta `Authorization: eqs <token>`. A sessão curta é opaca, expira por `TR4_EQUALIZADOR_SESSION_TTL_SECONDS` e é renovada enquanto houver atividade válida e não contém ID Telegram codificado. As rotas validam assinatura e `auth_date` no backend, conferem allowlist por variável e aplicam `TR4_EQUALIZADOR_CANAIS` em negação por padrão. A resposta retorna aliases públicos, nomes públicos, `@username` público quando existir, link `https://t.me/<username>` quando aplicável, perfis, canais concedidos, títulos de grupos e diagnóstico de direitos reais do bot. IDs numéricos continuam internos; a interface não usa link interno por ID do Telegram.

A rota de permissões do bot exige o canal crítico `grupo.afinar` e chama a Bot API em modo leitura (`getMe` e `getChatMember`) para verificar se o bot está como administrador no grupo e quais direitos estão disponíveis.

Na fase 5 entram ajustes leves por API, sempre com `Authorization: tma <Telegram.WebApp.initData>`, canal concedido, `grp_ref`, `msg_ref` ou `alvo_ref`. A interface pública não aceita `user_id`, `chat_id` nem `message_id`. Esses identificadores são resolvidos apenas no backend a partir das tabelas internas `eq_mensagens` e `eq_alvos`.

Rotas operacionais da fase 5:

```text
POST /equalizador/api/palcos/{grp_ref}/mensagens/apagar
POST /equalizador/api/palcos/{grp_ref}/membros/silenciar
POST /equalizador/api/palcos/{grp_ref}/membros/liberar
POST /equalizador/api/palcos/{grp_ref}/membros/remover
POST /equalizador/api/palcos/{grp_ref}/membros/reintegrar
POST /equalizador/api/palcos/{grp_ref}/fixados/criar
POST /equalizador/api/palcos/{grp_ref}/fixados/remover
POST /equalizador/api/palcos/{grp_ref}/convites/criar
GET  /equalizador/api/historico
```

Cada ajuste valida o direito real do bot antes da chamada Bot API e registra `eq_historico` com resumo público sanitizado. O payload técnico fica oculto da API comum.

Na fase 6 entram ações críticas restritas ao administrador principal, com confirmação explícita `CONFIRMAR AJUSTE`. Elas continuam usando aliases públicos e histórico sanitizado. `TR4_EQUALIZADOR_CANAIS` permanece como fonte de concessão; a interface não edita variáveis de ambiente.

Rotas críticas da fase 6:

```text
POST /equalizador/api/palcos/{grp_ref}/silencio/ativar
POST /equalizador/api/palcos/{grp_ref}/transmissao/enviar
GET  /equalizador/api/historico/exportar
GET  /equalizador/api/canais/distribuicao
```

`silencio.ativar` usa `setChatPermissions` para restringir permissões padrão de não administradores no grupo. `transmissao.enviar` usa `sendMessage` e registra a mensagem enviada como `msg_ref` quando a Bot API retorna `message_id`. A exportação de histórico retorna somente dados públicos; `payload_tecnico_json` não é exposto. A distribuição de canais mostra aliases (`usr_ref`, `grp_ref`) e escopos musicais, nunca IDs numéricos.

Na fase 7 entram os reforços de hardening: rate limit por operador (`TR4_EQUALIZADOR_RATE_LIMIT_PER_MINUTE`, padrão 120/min; Maestro não consome cota em rotas de ação), sessão curta opaca, trava de mesa para impedir ações concorrentes sobre o mesmo grupo/ajuste, logs operacionais sanitizados e estado do Equalizador em `/readyz`. Logs do Equalizador usam aliases como `usr_...` e `grp_...`; payloads, IDs numéricos e `message_id` não são enviados aos logs públicos; `@username` público pode aparecer na interface quando já conhecido, com link t.me.


## Validação

```bash
python -m compileall app scripts tests
PYTHONPATH=. python scripts/smoke_imports.py
PYTHONPATH=. pytest -q
```


<!-- TR4_DATABASE_RAILWAY_NOTE -->
## Railway / SQLite

TR4 music-only is SQLite-only. For Railway, use a persistent volume mounted at `/app/data`.
Set `TR3_DATABASE_URL=sqlite:////app/data/app.db` when possible. If an older Postgres `DATABASE_URL` remains from a previous service, TR4 ignores it unless it is already a SQLite URL.


Formato de `TR4_EQUALIZADOR_CANAIS`:

```text
telegram_user_id:telegram_chat_id:canal1,canal2;telegram_user_id:*:grupo.ver,canais.ver
```

Curingas são permitidos com `*`. Exemplo para Administrador principal com todos os canais em todos os grupos configurados:

```text
8505890439:*:*
```

Sem `TR4_EQUALIZADOR_CANAIS`, o padrão é negar canais. `TR4_EQUALIZADOR_MAESTRO_IDS` e `TR4_EQUALIZADOR_OPERADOR_IDS` identificam quem pode entrar; os canais definem o que cada pessoa pode ver ou usar. Canais críticos continuam restritos ao administrador principal mesmo quando um operador recebe `*`.


## Release operacional do Equalizador

A Fase 54.8 consolida a reorganização visual e funcional do Equalizador para deploy final no Railway. A etapa não adiciona novo poder além das fases 54.1 a 54.7; ela fecha documentação, variáveis, validação e roteiro de aplicação.

A Fase 8 não adiciona novos poderes de moderação. Ela consolida deploy, variáveis finais, smoke test, rollback e validação pré-release. O guia completo está em `docs/EQUALIZADOR_RELEASE_OPERACIONAL.md`.

Checklist recomendado antes do deploy:

```bash
python -m compileall app scripts tests
PYTHONPATH=. python scripts/equalizador_release_check.py --strict
PYTHONPATH=. python scripts/smoke_imports.py
PYTHONPATH=. pytest -q
```

Rollback lógico preferencial:

```text
TR4_EQUALIZADOR_ENABLED=false
```

Depois reinicie/redeploie o serviço. O router `/equalizador` deixa de ser registrado e a parte musical segue ativa.

### Equalizador — Etapa 27

O Administração crítica passou a depender das permissões do bot também na interface: `silencio.ativar` exige `can_restrict_members` e `transmissao.enviar` exige `can_manage_chat` antes de habilitar os botões. Erros críticos agora retornam mensagens públicas específicas e sanitizadas, e a exportação de histórico informa total de registros sem expor payload técnico.

### Equalizador — Etapa 29

A interface do Equalizador recebeu polimento final para uso mobile: status da Mesa, estados vazios para mensagens e membros, nomes públicos de canais na distribuição, resumo visual de Permissões do bot, mensagens de erro sanitizadas no frontend e bloqueio operacional mais explícito quando a Permissões do bot não está carregada. Esta etapa não adiciona novos poderes; apenas melhora usabilidade, clareza e segurança visual.

### Etapa 42 — Configuração amigável do Administrador principal

Esta etapa adiciona um assistente visual de configuração dentro do Equalizador. O Administrador principal passa a revisar e montar a configuração por campos, sem editar Raw Editor durante o uso normal.

O app continua sem alterar variáveis do Railway diretamente. Ao final, o Administrador principal gera um bloco Raw Editor para copiar e aplicar manualmente, preservando rollback e evitando duplicidade de chaves.

Inclui:

- campos para Mini App, status ligado/desligado, Administrador principals, Operadores, Grupos ativos e rate limit;
- campo de aliases por linha no formato `nome=-100...`;
- campo de canais por operador;
- endpoint `POST /equalizador/api/configuracao/raw-preview` restrito ao administrador principal;
- geração de Raw Editor somente no final;
- avisos quando houver grupo sem alias ou alias fora da lista ativa.

### Fase 52 — Consolidar app corrigido

Esta fase consolida a auditoria visual: operador, administradores, bots, membros, pedidos de entrada, canais remetentes, distribuição, histórico e seletores passam a priorizar nome público e `@username` público quando conhecido. Quando há username válido, a interface usa `https://t.me/<username>`; quando não há, exibe apenas o nome público. A interface não usa link interno por ID do Telegram para contato.

Os botões foram classificados por finalidade sem depender só de cor: verde para criar/aprovar/liberar, azul para organizar/editar/fixar/reabrir, laranja para atenção/configuração/transmissão e vermelho para apagar/remover/banir/rebaixar/recusar. O texto do botão permanece explícito.

A foto do bot e a foto do grupo agora usam fallback visual e cache de indisponibilidade, evitando repetição de chamadas quando a Bot API ou o grupo não disponibiliza foto pública.


### Fase 54.8 — Consolidação final Railway

Esta etapa fecha o pacote das fases 54.1 a 54.7 para aplicação em GitHub/Railway. O Equalizador fica organizado em janelas internas, com maior contraste visual, perfil do grupo com foto, mensagens/fixação, pessoas/administradores, convites/tópicos, diagnóstico real de permissões e normalização sanitizada de erros Telegram.

Para preservar tokens Spotify/Last.fm e sessões musicais existentes, use o SQLite persistente antigo no volume. O caminho recomendado é `TR3_DATABASE_URL=sqlite:////app/data/app.db`. Se o banco real antigo tiver outro nome, a variável deve apontar exatamente para esse arquivo, sem criar banco novo.

Guia operacional: `docs/FASE54_8_CONSOLIDACAO_RAILWAY.md`.


## Fase 55.7 — Reações, auditoria e reactors

Adiciona janela Reações no Equalizador, auditoria sanitizada de `message_reaction`, seleção de reactors recentes e silêncio de reactor em modo conservador, sem expor ID real na interface.

## Fase 58-59 consolidada — UI de lote e erros estruturados

Esta fase integra no Mini App a operação real de apagar mensagens em lote criada na fase 57. A tela de Mensagens agora possui seleção múltipla por `msg_ref`, mantém os IDs reais no servidor e envia uma única requisição para `/equalizador/api/palcos/{grp_ref}/mensagens/apagar-lote`.

Também foi reforçado o bloqueio preventivo de janelas quando o operador não tem canal concedido ou quando o bot não tem direito real confirmado no Telegram. Isso reduz cliques que terminariam em `403`, `409` ou `428` previsíveis.

As respostas de erro da Mesa agora preservam detalhes estruturados quando a falha vem do Telegram, usando categorias sanitizadas como `bot_lacks_permissions`, `target_not_admin`, `target_already_admin`, `target_is_creator`, `rate_limit`, `bad_request`, `conflict` e `telegram_unavailable`. Tokens, IDs e payloads internos seguem ocultos.

## Fase 60 — Auditoria final de estabilização

Auditoria final da sequência 56–59, sem novas funcionalidades. Confirma SQLite/WAL, DDX persistente, endpoint seguro de apagamento em lote, UX preventiva por permissão, erros Telegram estruturados e fechamento de pools HTTP. Inclui `scripts/equalizador_phase60_audit.py`, `tests/test_equalizador_phase60_auditoria.py` e o memorial técnico `docs/FASE60_AUDITORIA_FINAL.md`.

