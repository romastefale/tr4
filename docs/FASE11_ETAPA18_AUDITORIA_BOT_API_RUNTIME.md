# FASE 11 — ETAPA 18 — Auditoria Bot API + runtime

## Objetivo

Auditar o pacote final da Fase 11 contra a documentação oficial atual da Telegram Bot API e contra o código real, com foco em métodos, parâmetros, permissões e riscos de runtime.

## Fontes oficiais verificadas

- Telegram Bot API — `https://core.telegram.org/bots/api`
- Consulta em 2026-06-10.

Pontos oficiais relevantes:

- `sendMessage` envia texto de 1 a 4096 caracteres e retorna `Message`.
- `sendPhoto` envia foto, aceita legenda de 0 a 1024 caracteres e retorna `Message`.
- `sendMessage` usa `link_preview_options`; `disable_web_page_preview` não aparece mais na documentação atual.
- `deleteMessage` tem limitações, incluindo janela de 48 horas e direitos administrativos conforme tipo de chat.
- `banChatMember` aceita `revoke_messages`.
- `unbanChatMember` aceita `only_if_banned`.
- `createChatInviteLink` aceita `creates_join_request`; quando `creates_join_request=True`, `member_limit` não pode ser especificado.
- `pinChatMessage`/`unpinChatMessage` exigem `can_pin_messages` em supergrupos ou direito equivalente em canais.
- `deleteMessageReaction` e `deleteAllMessageReactions` exigem `can_delete_messages`.
- `setChatMemberTag` exige `can_manage_tags`.

## Correções aplicadas nesta etapa

### 1. Payloads diretos de link preview

Arquivos corrigidos:

- `app/equalizador/mesa.py`
- `app/equalizador/maestro.py`
- `app/equalizador/multimidia.py`

Antes, chamadas HTTP diretas ao Bot API ainda usavam `disable_web_page_preview`. A documentação atual expõe `link_preview_options`; por isso, os payloads diretos do Equalizador foram ajustados para:

```python
"link_preview_options": {"is_disabled": True}
```

ou para valor dinâmico conforme `sem_preview`.

### 2. Legenda de foto do governante

Em `mensagens.enviar_foto`, a legenda vinha com `parse_mode="HTML"`, embora o texto fosse digitado pelo governante sem escape obrigatório. Isso podia gerar erro de parsing quando a legenda contivesse `<`, `>`, `&` ou marcação incompleta.

Correção: a legenda do governante passou a ser enviada como texto simples, sem `parse_mode`.

### 3. Convite com solicitação forçado também no backend

O escopo decidiu que o Web App governante cria convite único com solicitação/aprovação. O frontend já mandava `solicitar_aprovacao=true`, mas o backend ainda aceitava chamada direta com `member_limit` e sem join request.

Correção: `convites.criar` agora monta sempre:

```python
{"creates_join_request": True}
```

E ignora `member_limit`, porque a Bot API não permite `member_limit` junto de `creates_join_request=True`.

### 4. Teste de compatibilidade criado

Novo teste:

- `tests/test_phase11_etapa18_bot_api_compat.py`

Ele valida por inspeção estática:

- payload direto usa `link_preview_options`;
- `disable_web_page_preview` não aparece nos payloads diretos Equalizador revisados;
- legenda de foto governante não ativa `parse_mode`;
- convite backend é sempre `creates_join_request=True` sem `member_limit`.

### 5. `phase11_final_check.sh` atualizado

O script final passou a rodar também o teste da Etapa 18.

## Matriz Bot API x TR4

| Área | Método Telegram | Arquivo principal | Status |
|---|---|---|---|
| Texto | `sendMessage` | `mesa.py`, `maestro.py`, `router.py`, `music_broadcast.py` | Compatível; payload direto atualizado para `link_preview_options` onde aplicável. |
| Foto | `sendPhoto` | `mesa.py`, `music_broadcast.py`, `router.py` | Compatível; legenda do governante virou texto simples. |
| Apagar | `deleteMessage` | `mesa.py` | Compatível; janela de 48h já é checada por `mensagem_fora_da_janela_apagar`. |
| Ban | `banChatMember` | `mesa.py` | Compatível; usa `revoke_messages=True`. |
| Unban | `unbanChatMember` | `mesa.py` | Compatível; usa `only_if_banned`. |
| Restrição | `restrictChatMember` | `mesa.py`, `reacoes.py` | Compatível; exige `can_restrict_members`. |
| Fixar | `pinChatMessage` | `mesa.py`, `maestro.py`, `music_broadcast.py` | Compatível; exige `can_pin_messages` quando necessário. |
| Convite | `createChatInviteLink` | `mesa.py` | Corrigido; sempre `creates_join_request=True` e sem `member_limit`. |
| Editar/revogar convite | `editChatInviteLink`, `revokeChatInviteLink` | `entradas.py` | Compatível; owner-only no escopo atual. |
| Exportar link primário | `exportChatInviteLink` | `entradas.py` | Compatível; owner-only e canal `convites.ver`. |
| Reações | `deleteMessageReaction`, `deleteAllMessageReactions` | `avancado.py` | Compatível e mantido fora do governante. |
| Tags | `setChatMemberTag` | `avancado.py` | Compatível e mantido fora do governante. |

## Limitações remanescentes

- Ainda existem usos de `disable_web_page_preview=True` em handlers aiogram fora do payload HTTP direto do Equalizador. Eles não foram alterados nesta etapa para evitar mudança ampla em comandos musicais legados sem validar assinatura da versão instalada do aiogram no ambiente real. Recomenda-se validar no Termux/Railway e migrar depois para `LinkPreviewOptions` onde aplicável.
- A suíte completa ainda precisa rodar em ambiente com `SQLAlchemy` instalado. Neste container, os testes específicos passam, mas alguns ficam `skipped`.
- A compatibilidade real de WebView/cookie precisa ser testada no Telegram, porque validação local não reproduz o ambiente de Mini App.

## Resultado local

- `py_compile`: OK
- Validação HTML/JS/IDs: OK
- `node --check`: OK
- `release_check`: EXIT 0
- `phase11_final_check.sh`: OK
- Testes específicos: 69 passed, 14 skipped

## Conclusão

A Etapa 18 corrigiu os pontos que tinham risco direto de incompatibilidade com a documentação atual da Bot API nos payloads do Equalizador: preview de link, legenda HTML indevida em foto do governante e convite com `member_limit` concorrendo com `creates_join_request`.

O pacote ainda deve ser validado em Termux/Railway com dependências completas e no Telegram real antes do deploy amplo.
