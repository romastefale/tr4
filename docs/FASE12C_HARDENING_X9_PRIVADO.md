# Fase 12C — hardening do FSM privado + X9 silencioso

## Veredito

Esta etapa substitui a 12B como pacote recomendado antes de teste real. A arquitetura continua igual: Web App como player, grupo sem menu operacional, moderação/configuração via DM e X9 apenas como observador silencioso. O foco foi reduzir risco de vazamento, crescimento de banco e callback indevido.

## Correções aplicadas

### 1. X9 com allowlist conservadora

O X9 passivo não aprende mais qualquer grupo desconhecido por padrão. Ele só retém contexto quando:

- o grupo está em `TR4_EQUALIZADOR_PALCO_IDS`;
- o grupo já existe em `eq_palcos` com `habilitado=1`;
- `TR4_FSM_X9_CAPTURE_UNKNOWN_GROUPS=true` foi definido intencionalmente.

Triggers mínimos no grupo ainda podem capturar contexto se o usuário for owner/operador configurado ou administrador real do grupo. Mesmo assim, nenhum menu é exibido no grupo.

### 2. Retenção e limite do X9

Novas variáveis:

- `TR4_FSM_X9_MESSAGE_TTL_SECONDS`, padrão `46 * 60 * 60`;
- `TR4_FSM_X9_MAX_MESSAGES_PER_GROUP`, padrão `200`;
- `TR4_FSM_X9_SUMMARY_MAX_CHARS`, padrão `80`;
- `TR4_FSM_X9_CAPTURE_UNKNOWN_GROUPS`, padrão `false`.

Mensagens antigas são marcadas como inativas e não aparecem no FSM privado. Isso reduz acúmulo e respeita a janela operacional prática para ações como apagar mensagem.

### 3. Sem vazamento de referência para não autorizado

O trigger de grupo não envia `msg_ref` por DM antes de autorização. O usuário recebe, no máximo, um aviso genérico em DM quando for autorizado. Referências concretas só aparecem dentro de `/tmod`, após seleção privada e validação.

### 4. Tokens de callback vinculados

Tokens do fluxo de moderação agora carregam:

- `user_id` do operador que criou o token;
- `pending_action` definido na etapa de confirmação.

Callback de outro usuário ou confirmação com ação diferente é recusado.

### 5. Listagem privada só mostra mensagens operáveis recentes

`list_recent_messages` e `get_message_by_ref` exigem `telegram_message_date` dentro da janela do X9. Mensagens sem data ou antigas não aparecem para ação.

## Fontes técnicas usadas

- Telegram Bot API: `deleteMessage` documenta limitações, incluindo a regra de menos de 48 horas para apagar mensagens.
- Telegram Mini Apps: `initDataUnsafe` não deve ser confiado; `initData` deve ser validado no servidor.
- Telegram Bot Features: escopos de comandos são apenas apresentação; o backend deve validar comando e autorização.

## Arquivos alterados

- `app/config/settings.py`
- `app/fsm_tigrao/context.py`
- `app/fsm_tigrao/router.py`
- `app/fsm_tigrao/x9.py`
- `scripts/phase11_final_check.sh`
- `tests/test_fsm_private_x9_hardening.py`
- `docs/FASE12C_HARDENING_X9_PRIVADO.md`

## Validação local

- `py_compile`: OK
- `validate_equalizador_embedded_html.py`: OK
- `equalizador_release_check.py`: OK com avisos de ambiente local
- `phase11_final_check.sh`: OK, `99 passed, 14 skipped`
- teste focal FSM/X9: OK, `15 passed, 1 skipped`

## Recomendações para teste real

1. Aplicar este pacote, não a 12B original.
2. Garantir que `TR4_EQUALIZADOR_MAESTRO_IDS` e/ou `TR4_EQUALIZADOR_OPERADOR_IDS` estejam corretos.
3. Se quiser X9 automático somente em grupos específicos, preencher `TR4_EQUALIZADOR_PALCO_IDS`.
4. Não ativar `TR4_FSM_X9_CAPTURE_UNKNOWN_GROUPS=true` em produção antes de validar privacidade e volume.
5. Testar `/tmod` e `/tgrp` no privado.
6. Em grupo, testar trigger mínimo e confirmar que nenhum menu aparece.
