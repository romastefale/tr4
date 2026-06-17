# Relatório Codex — Tigrão FSM — Etapa 03
## 1. Resumo objetivo
Conectei o plugin `app/plugins/tigrao_fsm/` ao TR4 real atrás de `TIGRAO_FSM_ENABLED`, preservando o fluxo musical quando a flag está desligada.

## 2. Arquivos criados
- `tests/test_tigrao_fsm_stage3_static.py`
- `artifacts/codex_reports/ETAPA_03_TIGRAO_FSM_RELATORIO.md`
- `artifacts/codex_reports/ETAPA_03_TIGRAO_FSM.diff`
- `artifacts/codex_reports/ETAPA_03_TIGRAO_FSM_STATUS.txt`

## 3. Arquivos alterados
- `app/main.py`
- `app/config/settings.py`
- `app/plugins/tigrao_fsm/__init__.py`
- `app/plugins/tigrao_fsm/plugin.py`
- `app/plugins/tigrao_fsm/mount.py`
- `app/plugins/tigrao_fsm/keyboards.py`
- `app/plugins/tigrao_fsm/routers/panel.py`
- `tests/test_tigrao_fsm_skeleton.py`
- `tests/test_tigrao_fsm_stage2_static.py`

## 4. Arquivos removidos
Nenhum.

## 5. Pontos de conexão no TR4
- `settings.py`: adiciona `TIGRAO_FSM_ENABLED` com default `False` e `TIGRAO_FSM_MODERATOR_IDS`; autorização usa `CODE_OWNER_IDS + TIGRAO_FSM_MODERATOR_IDS`.
- `main.py`: importa apenas `build_tigrao_fsm_plugin` da interface pública do pacote.
- `_configure_telegram_bot_background`: monta `tigrao_plugin.mount(dispatcher)` somente com flag ligada, depois dos routers/handlers musicais específicos e antes de `_register_handlers(dispatcher)`.
- `/webhook`: após lembrar grupo/usuários, executa `set_current_user` e `before_dispatch` somente com flag ligada; se consumido, não chama `dispatcher.feed_update`.

## 6. Feature flag
- `TIGRAO_FSM_ENABLED=0` ou ausente: plugin não é instanciado para runtime, não monta router, não roda `before_dispatch`, não adiciona allowed_updates extras.
- `TIGRAO_FSM_ENABLED=1`: plugin é construído, montado no dispatcher e recebe ponte antes do dispatch normal.

## 7. allowed_updates
- Flag desligada: mantém `dispatcher.resolve_used_update_types()` + `chosen_inline_result`.
- Flag ligada: adiciona `chat_join_request`, `chat_member`, `message_reaction`, `message_reaction_count` e `callback_query`, sem remover os updates resolvidos pelo dispatcher.

## 8. Painel /tigrao
- Usuário não autorizado: ignorado.
- Autorizado em DM: responde com home `Tigrão` e botões `Selecionar grupo`/`Fechar`.
- Autorizado em grupo/supergrupo: não responde no grupo; tenta enviar a home por DM; falha de DM é logada em debug.

## 9. Callbacks e sessão
- Sessões usam `state.py`, `session_id` curto e timeout de 15 minutos.
- Callback usa formato curto `tgf:<sid>:<ação>`.
- Seleção de grupo grava grupos em `session.payload["groups"]` e usa ações `g0` a `g49`; não coloca `chat_id` bruto no callback.
- Ações mínimas conectadas: `home`, `grp`, `back`, `close`; também há placeholders seguros de logs e solicitações.

## 10. before_dispatch
Roda somente com `TIGRAO_FSM_ENABLED=1`. Se retornar `True`, consome update e pula `dispatcher.feed_update`; se retornar `False`, segue fluxo normal. Exceções são logadas como `TIGRAO_FSM_BEFORE_DISPATCH_ERROR` e o update segue para o dispatcher normal. DDX permanece seguro/no-op sem configuração ativa, filtro explícito e permissão real.

## 11. Garantias de isolamento musical
`main.py` foi alterado apenas para bridge pública/feature flag. Não alterei `app/bot/telegram.py` nem os arquivos musicais proibidos. O painel não toca em `/playing`, `/radiofm`, `/tnow`, `/tly`, inline musical ou WebApp musical.

## 12. Validações executadas
- `python -m compileall -q app` — passou.
- `python -m pytest -q tests/test_tigrao_fsm_skeleton.py` — 7 passed.
- `python -m pytest -q tests/test_tigrao_fsm_stage2_static.py` — 21 passed.
- `python -m pytest -q tests/test_tigrao_fsm_stage3_static.py` — 10 passed.

## 13. Testes que não rodaram
Não rodei a suíte completa fora do escopo; rodei todos os testes obrigatórios solicitados.

## 14. Riscos e pendências
- Pendências seguras: telas completas de logs, ações destrutivas, aprovação manual/automática persistente e X9 real ficam para etapa posterior.
- Riscos técnicos: `list_groups` é leitura de tabela musical existente; falhas são tratadas com tela vazia.
- Não implementado por falta de storage/runtime persistente completo: DDX ativo configurável, aprovação/recusa automática de solicitações e dados reais de logs.

## 15. Conclusão
Concluída.
