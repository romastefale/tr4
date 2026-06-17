# Relatório Codex — Tigrão FSM — Etapa 02
## 1. Resumo objetivo
Etapa 02 concluída com atualização isolada do plugin `app/plugins/tigrao_fsm/`, sem conexão ao `main.py`, sem montagem no dispatcher global e sem alteração do fluxo musical do TR4.

## 2. Correções feitas sobre a Etapa 1
- Callbacks corrigidos com limite de 64 bytes, validação UTF-8, namespace `tgf:`, tokens internos seguros, rejeição de vazio, `:` interno, partes ambíguas e ações fora do formato permitido.
- Função de superfície renomeada para `is_private_panel_surface`, retornando `True` somente para `private`.
- Botões reais preparados com fallback para `aiogram`, validação de ação única e suporte seguro a `style` quando disponível.
- Interface interna final exposta via `mount(dispatcher)`, `before_dispatch(bot, update)` e `set_current_user(user_id)`, ainda isolada.
- Testes estáticos ampliados para callback, botões, superfície DM-only, parsers, X9 e isolamento.

## 3. Arquivos criados
- `app/plugins/tigrao_fsm/parsers.py`
- `app/plugins/tigrao_fsm/models.py`
- `app/plugins/tigrao_fsm/services.py`
- `tests/test_tigrao_fsm_stage2_static.py`
- `artifacts/codex_reports/ETAPA_02_TIGRAO_FSM_RELATORIO.md`
- `artifacts/codex_reports/ETAPA_02_TIGRAO_FSM.diff`
- `artifacts/codex_reports/ETAPA_02_TIGRAO_FSM_STATUS.txt`

## 4. Arquivos alterados
- `app/plugins/tigrao_fsm/keyboards.py`
- `app/plugins/tigrao_fsm/permissions.py`
- `app/plugins/tigrao_fsm/plugin.py`
- `app/plugins/tigrao_fsm/mount.py`
- `app/plugins/tigrao_fsm/runtime/ddx_runtime.py`
- `tests/test_tigrao_fsm_skeleton.py`

## 5. Arquivos removidos
Nenhum.

## 6. Escopo aplicado
- Painel DM-only preparado internamente.
- Home limpa com botões `Selecionar grupo` e `Fechar`.
- Texto de grupo indisponível quando o bot não é administrador.
- Estrutura de permissões do bot e mapeamentos internos.
- Estruturas de join requests, autoaceite e logs.
- Link de solicitação preparado sem `member_limit` quando `creates_join_request=True`.
- Parser de múltiplos IDs positivos com inválidos e deduplicação preservando ordem.
- Serviço isolado para aceitar ID pendente salvo.
- Confirmação com ID Telegram e sem afirmar confirmação pós-entrada sem `chat_member`.
- Parser X9 isolado que só aceita prefixo explícito `x9`.
- Runtime DDX hard isolado via `before_dispatch`, ainda sem conexão real.

## 7. Escopo não aplicado
- Não houve conexão ao `main.py`.
- Não houve alteração em `app/bot/telegram.py`.
- Não houve ativação no dispatcher real.
- Não houve ativação real de X9, DDX ou webhook.
- Não houve alteração de `/playing`, `/radiofm`, `/tnow`, `/tly`, inline musical ou WebApp musical.

## 8. Garantias de isolamento musical
- `app/main.py`: não tocado para importar ou montar o Tigrão.
- `app/bot/telegram.py`: não alterado.
- `app/bot/playing*`: não alterado.
- `app/bot/radiofm.py`: não alterado.
- `app/bot/tnow.py`: não alterado.
- `app/bot/tly.py`: não alterado.
- `app/bot/music_inline.py`: não alterado.
- `app/web_music/`: não alterado.

## 9. Segurança aplicada
- `callback_data` limitado a 64 bytes e validado por bytes UTF-8.
- Payload grande mantido fora do callback; callback contém apenas sessão e ação.
- Painel somente por DM, sem fallback público em grupo.
- Autoaceite exige ID numérico positivo; `@username`, texto, IDs negativos e chat IDs negativos são rejeitados.

## 10. Telegram/Bot API aplicado
- `callback_data`: respeitado contrato de 1 a 64 bytes.
- `style`: preparado para `primary`, `success` e `danger` quando aceito pela versão instalada; fallback sem `style` quando incompatível.
- `createChatInviteLink`: quando `creates_join_request=True`, o helper remove `member_limit`.
- `approve/decline` e `chat_join_request`: estruturas e permissões usam `can_invite_users` como permissão necessária.
- `user_chat_id`: armazenável como inteiro de 64 bits e modelado como dado auxiliar para tentativa de DM por até 5 minutos, sem ser chave operacional de aprovação.

## 11. Validações executadas
- `python -m compileall -q app`: passou.
- `python -m pytest -q tests/test_tigrao_fsm_skeleton.py`: passou, 7 testes.
- `python -m pytest -q tests/test_tigrao_fsm_stage2_static.py`: passou, 12 testes.

## 12. Testes que não rodaram
Nenhum teste obrigatório deixou de rodar.

## 13. Riscos ou pendências
- Etapa 3 ainda deve conectar o plugin ao dispatcher real com revisão humana.
- Storage persistente real ainda precisa ser integrado.
- Aprovação/declínio reais dependem de permissões do bot em runtime.
- Logs finais e telas de abas ainda precisam de integração real.

## 14. Como revisar esta etapa
- Revisar `app/plugins/tigrao_fsm/keyboards.py` para segurança de callbacks e botões.
- Revisar `app/plugins/tigrao_fsm/permissions.py` para superfície DM-only e permissões.
- Revisar `app/plugins/tigrao_fsm/parsers.py` para IDs e X9.
- Rodar os três comandos de validação da seção 11.
- Confirmar que `app/main.py`, `app/bot/telegram.py` e arquivos musicais não receberam import ou referência ao Tigrão.

## 15. Conclusão
Concluída. A Etapa 02 foi implementada em modo isolado, sem avançar para a Etapa 3.
