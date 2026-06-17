# Relatório Codex — Tigrão FSM — Etapa 03
## 1. Resumo objetivo
Correção de entrega e comprovação da Etapa 03. Confirmei que `tests/test_tigrao_fsm_stage3_static.py` existe no repositório e está versionado no commit da etapa. Regerei os artefatos para remover a inconsistência entre relatório, diff e status.

## 2. Arquivos criados
Nenhum arquivo novo nesta correção. O arquivo `tests/test_tigrao_fsm_stage3_static.py` já existe e está presente no repositório.

## 3. Arquivos alterados
- `artifacts/codex_reports/ETAPA_03_TIGRAO_FSM_RELATORIO.md`
- `artifacts/codex_reports/ETAPA_03_TIGRAO_FSM.diff`
- `artifacts/codex_reports/ETAPA_03_TIGRAO_FSM_STATUS.txt`

## 4. Arquivos removidos
Nenhum.

## 5. Pontos de conexão no TR4
Não houve alteração de código de runtime nesta correção. A conexão permanece em `app/main.py` via interface pública `build_tigrao_fsm_plugin`, com montagem e `before_dispatch` condicionados a `TIGRAO_FSM_ENABLED`. A configuração permanece em `app/config/settings.py` com `TIGRAO_FSM_ENABLED` default `False` e `TIGRAO_FSM_MODERATOR_IDS`.

## 6. Feature flag
Sem mudança nesta correção:
- `TIGRAO_FSM_ENABLED=0` ou ausente: sem montagem do router Tigrão, sem `before_dispatch` Tigrão e sem allowed_updates extras do Tigrão.
- `TIGRAO_FSM_ENABLED=1`: monta o plugin, executa `set_current_user`, roda `before_dispatch` antes do dispatcher normal e respeita consumo seguro do update.

## 7. allowed_updates
Sem mudança nesta correção. O helper preserva `dispatcher.resolve_used_update_types()` + `chosen_inline_result` e adiciona `chat_join_request`, `chat_member`, `message_reaction`, `message_reaction_count` e `callback_query` somente quando a flag está ligada.

## 8. Painel /tigrao
Sem mudança nesta correção. O painel mantém DM para autorizado, nenhuma resposta pública em grupo/supergrupo, ignore para não autorizado e fallback seguro em falhas de DM.

## 9. Callbacks e sessão
Sem mudança nesta correção. Os callbacks continuam usando `tgf:<sid>:<ação>`, sessão no servidor e índices `g0` a `g49`, sem `chat_id` bruto em callback.

## 10. before_dispatch
Sem mudança nesta correção. `before_dispatch` roda apenas atrás da feature flag; se consumir, pula `dispatcher.feed_update`; se falhar, loga erro e deixa o update seguir.

## 11. Garantias de isolamento musical
Nesta correção não alterei `app/bot/telegram.py`, arquivos musicais, WebApp musical ou runtime musical. A correção ficou restrita aos artefatos de comprovação.

## 12. Validações executadas
- `test -f tests/test_tigrao_fsm_stage3_static.py` — confirmou que o arquivo existe.
- `git ls-tree -r --name-only HEAD tests | rg 'tigrao_fsm_stage3|tigrao_fsm_stage2|skeleton'` — confirmou que `tests/test_tigrao_fsm_stage3_static.py` está versionado no commit da etapa.
- `python -m compileall -q app` — passou.
- `python -m pytest -q tests/test_tigrao_fsm_skeleton.py` — 7 passed.
- `python -m pytest -q tests/test_tigrao_fsm_stage2_static.py` — 21 passed.
- `python -m pytest -q tests/test_tigrao_fsm_stage3_static.py` — 10 passed.

## 13. Testes que não rodaram
Não rodei suíte completa fora do escopo; rodei exatamente os comandos solicitados para a correção.

## 14. Riscos e pendências
- Pendência corrigida: o diff regenerado agora contém `tests/test_tigrao_fsm_stage3_static.py` e `artifacts/codex_reports/ETAPA_03_TIGRAO_FSM_STATUS.txt`.
- Sem novos riscos técnicos, pois não houve alteração de runtime nesta correção.
- Pendências funcionais da Etapa 03 permanecem as já documentadas: logs completos, ações destrutivas, aprovação persistente e X9 real ficam para etapa posterior.

## 15. Conclusão
Correção de entrega concluída. A Etapa 03 permanece sem avanço funcional adicional; apenas a comprovação foi regenerada.
