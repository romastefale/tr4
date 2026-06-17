# Revisão ChatGPT — Tigrão FSM — Etapas 1 e 2

## 1. Base usada

A revisão usou exclusivamente o ZIP enviado nesta rodada: `/mnt/data/tr4-fsm 2.zip`, extraído em sandbox. Não usei memória operacional como fonte de verdade do código. Quando houve dúvida técnica de Telegram/aiogram, usei documentação oficial atual.

## 2. Como analisei

1. Extraí o ZIP em sandbox.
2. Localizei o plugin `app/plugins/tigrao_fsm/` e os testes `tests/test_tigrao_fsm_skeleton.py` e `tests/test_tigrao_fsm_stage2_static.py`.
3. Li os arquivos do plugin, com foco em:
   - `keyboards.py`
   - `permissions.py`
   - `parsers.py`
   - `plugin.py`
   - `runtime/ddx_runtime.py`
   - `services.py`
   - testes da etapa 1 e 2
4. Conferi a documentação atual do aiogram 3.28.1 e da Telegram Bot API.
5. Rodei validações locais.
6. Corrigi apenas o ponto que ainda estava tecnicamente incorreto dentro do escopo das etapas 1 e 2.

## 3. Erro encontrado

O arquivo `app/plugins/tigrao_fsm/keyboards.py` ainda tinha fallback inseguro para `copy_text`.

O caso normal com aiogram atual estava certo: quando `CopyTextButton` existia, o código usava `CopyTextButton(text=...)`. Porém, se `CopyTextButton` não existisse ou fosse incompatível, o código ainda poderia tentar montar `InlineKeyboardButton` com `copy_text` como string. Isso é incorreto: em aiogram 3.28.1, `InlineKeyboardButton.copy_text` espera `CopyTextButton`, não string.

## 4. Correção aplicada

Corrigi `keyboards.py` para:

- carregar opcionalmente `CopyTextButton`, `InlineKeyboardButton` e `InlineKeyboardMarkup` em variáveis internas;
- criar `_copy_text_button(value)` que retorna `CopyTextButton(text=value)` quando suportado;
- retornar `TigraoButtonSpec` como fallback seguro se `CopyTextButton` não existir ou se `InlineKeyboardButton` não aceitar `copy_text`;
- nunca passar string crua para `InlineKeyboardButton.copy_text`;
- manter fallback de `style` sem quebrar runtimes antigos.

## 5. Testes adicionados

Adicionei dois testes em `tests/test_tigrao_fsm_stage2_static.py`:

1. `test_copy_text_fallback_never_passes_string_to_inline_keyboard`
   - simula ausência de `CopyTextButton`;
   - garante que `InlineKeyboardButton` não recebe `copy_text` string;
   - garante retorno seguro como `TigraoButtonSpec`.

2. `test_copy_text_fallback_on_inline_keyboard_type_error`
   - simula runtime legado que rejeita `copy_text`;
   - garante fallback seguro para `TigraoButtonSpec`.

## 6. O que não alterei

Não alterei:

- `app/main.py`
- `app/bot/telegram.py`
- fluxo musical
- `/playing`
- `/radiofm`
- `/tnow`
- `/tly`
- inline musical
- WebApp musical
- dispatcher
- webhook
- DDX real
- X9 real
- solicitações reais em runtime

## 7. Validações executadas

Comandos executados dentro da árvore corrigida:

```bash
python -m compileall -q app
python -m pytest -q tests/test_tigrao_fsm_skeleton.py tests/test_tigrao_fsm_stage2_static.py
```

Resultado:

```text
28 passed
```

Também rodei teste manual do fallback de `copy_text` com `_AiogramCopyTextButton = None`; passou.

## 8. Fontes técnicas usadas

- aiogram 3.28.1: `InlineKeyboardButton` usa `copy_text: CopyTextButton | None`, `style` aceita `danger`, `success` ou `primary`, e `callback_data` é de 1 a 64 bytes.
- Telegram Bot API: `createChatInviteLink` com `creates_join_request=True` não pode usar `member_limit`; `approveChatJoinRequest` e `declineChatJoinRequest` exigem `can_invite_users`; `chat_join_request` exige `can_invite_users`; `user_chat_id` pode precisar de 64-bit e só permite contato por 5 minutos.

## 9. Arquivos alterados

- `app/plugins/tigrao_fsm/keyboards.py`
- `tests/test_tigrao_fsm_stage2_static.py`

## 10. Conclusão

A correção final das Etapas 1 e 2 foi aplicada dentro do escopo. O ponto técnico pendente em `copy_text` foi corrigido e coberto por teste. A base ficou pronta para revisão antes da Etapa 3, sem conectar o Tigrão FSM ao TR4 principal.
