# Relatório Codex — Tigrão FSM — Etapa 02B

## 1. Resumo objetivo
Correção curta da Etapa 2 aplicada somente nos caminhos permitidos, sem avançar para a Etapa 3 e sem conectar o Tigrão FSM ao `main.py`, ao dispatcher real ou ao fluxo musical.

## 2. Branch e base operacional
- Branch de trabalho usada pelo Codex: `work`.
- Target/base operacional informado para revisão humana: `fsm`.

## 3. Correções feitas
- `copy_text` agora valida conteúdo entre 1 e 256 caracteres e, quando `aiogram.types.CopyTextButton` está disponível, constrói `CopyTextButton(text=...)` antes de montar `InlineKeyboardButton`.
- `approve_pending_join_request` agora salva e retorna o mesmo texto detalhado, sem expressão condicional ambígua, com todos os campos exigidos para usuário com ou sem username.
- Runtime DDX isolado foi endurecido: não apaga sem `active=True`, sem filtro explícito, sem match em text/caption, sem permissões fornecidas ou sem `can_delete_messages=True`.
- Callbacks usam a constante central `CALLBACK_ACTIONS`, com ações curtas necessárias para a Etapa 3 e rejeição de ações fora da lista.
- Parser X9 agora aceita somente `x9` ou `x9 ` seguido de argumentos; rejeita `x9:`, `x9-`, `xx9` e números soltos.

## 4. Arquivos alterados
- `app/plugins/tigrao_fsm/keyboards.py`
- `app/plugins/tigrao_fsm/services.py`
- `app/plugins/tigrao_fsm/runtime/ddx_runtime.py`
- `app/plugins/tigrao_fsm/parsers.py`
- `tests/test_tigrao_fsm_stage2_static.py`
- `artifacts/codex_reports/ETAPA_02B_TIGRAO_FSM_RELATORIO.md`
- `artifacts/codex_reports/ETAPA_02B_TIGRAO_FSM.diff`
- `artifacts/codex_reports/ETAPA_02B_TIGRAO_FSM_STATUS.txt`

## 5. Arquivos fora do escopo permitido
Nenhum arquivo fora dos paths permitidos foi alterado nesta correção.

## 6. Garantias de isolamento
- `app/main.py`: não editado.
- `app/bot/telegram.py`: não editado.
- Fluxo musical, `/playing`, `/radiofm`, `/tnow`, `/tly`, inline musical e WebApp musical: não alterados.
- Plugin segue isolado; nenhuma montagem real no dispatcher foi adicionada.

## 7. STATUS SEM ARTIFACTS
Antes do commit, `STATUS SEM ARTIFACTS` não estava limpo porque continha exatamente as alterações de código/testes permitidas desta Etapa 02B. Após commit, a expectativa é que fique limpo sem contar artefatos. O arquivo de status desta etapa inclui a seção `STATUS SEM ARTIFACTS` solicitada.

## 8. Validações executadas
- `python -m compileall -q app`: passou.
- `python -m pytest -q tests/test_tigrao_fsm_skeleton.py`: passou, 7 testes.
- `python -m pytest -q tests/test_tigrao_fsm_stage2_static.py`: passou, 19 testes.

## 9. Testes adicionados
- Construção real/fallback seguro de botão `copy_text`.
- Validação de tamanho de `copy_text`.
- Ação futura válida e ação inválida de callback.
- Aprovação de join request com username e sem username.
- DDX não apaga sem filtro nem sem permissão.
- DDX não apaga quando texto/caption não batem no filtro.
- X9 rejeita `x9:`, `x9-`, `xx9` e números soltos.

## 10. Conclusão
Concluída em modo isolado, sem avançar para a Etapa 3.
