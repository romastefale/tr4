# Dossiê isolado — Tigrão FSM / TR3

Gerado em UTC: 2026-06-17T05:45:15Z  
Fonte real lida: `/mnt/data/TR3-0e5929e229be1bceaf6efad0cb484be7ee2338d0.zip`  
Raiz extraída: `/mnt/data/tr3_src/TR3-0e5929e229be1bceaf6efad0cb484be7ee2338d0`

## Objetivo deste arquivo isolado

Este pacote foi montado para não precisar abrir o repositório TR3 inteiro toda vez que o assunto for **Tigrão FSM**. Ele contém:

1. o pacote original completo `app/moderation_tigrao/`;
2. os arquivos externos que fazem acoplamento com o Tigrão;
3. snippets exatos de integração no `main.py`, `telegram.py` e `database.py`;
4. este relatório técnico consolidado;
5. um manifesto JSON com hashes, linhas, handlers, callbacks e referências externas.

O arquivo não aplica correções, não altera TR4 e não reescreve o Tigrão. É uma cópia técnica de estudo e isolamento.

## Fatos confirmados na leitura do ZIP

- O painel está concentrado em `app/moderation_tigrao/`, com 20 arquivos Python e 5112 linhas totais.
- O comando principal é `@router.message(Command("tigrao"))` em `app/moderation_tigrao/router.py`.
- O painel usa **botões coloridos** via `InlineKeyboardButton(..., style="primary"|"success"|"danger")` em `keyboards.py`.
- O painel usa **CopyTextButton** em `keyboards.py` para copiar link.
- O `requirements.txt` do ZIP declara `aiogram==3.27.0`, não 3.28. Se sua base atual roda 3.28, isso deve ser tratado como alvo de aplicação, não como fato deste ZIP.
- O Tigrão chamado de FSM **não usa FSM nativo do aiogram**. Ele usa FSM própria em `state.py`, com `TigrãoSession`, `_sessions` e `ContextVar`.
- O acoplamento crítico está no `app/main.py`, que importa routers, handlers diretos, preprocessadores DDX/DDX soft/NMW e chama tudo antes do `dispatcher.feed_update`.
- Há acoplamento também no `app/bot/telegram.py`: captura de reactions para `reaction_audit`, reserva de formato inline X9 e guard `owner_dialog_active` para não deixar o root handler musical consumir diálogo pendente do Tigrão.

## Árvore do pacote isolado

```text
tigrao_fsm_isolado_TR3/
  RELATORIO_TIGRAO_FSM.md
  MANIFESTO_TIGRAO_FSM.json
  fonte_original_tr3/app/moderation_tigrao/*.py
  contexto_dependencias_tr3/requirements.txt
  contexto_dependencias_tr3/app/main.py
  contexto_dependencias_tr3/app/bot/telegram.py
  contexto_dependencias_tr3/app/bot/new_member_watch_runtime.py
  contexto_dependencias_tr3/app/db/database.py
  contexto_dependencias_tr3/app/services/reaction_audit.py
  contexto_dependencias_tr3/app/services/new_member_watch.py
  contexto_dependencias_tr3/app/models/reaction_audit.py
  contexto_dependencias_tr3/app/models/new_member_watch.py
  contexto_dependencias_tr3/app/bot/music_extras.py
  contexto_dependencias_tr3/app/bot/songcharts.py
  contexto_dependencias_tr3/app/btb/router.py
  contexto_dependencias_tr3/app/btb/state.py
  snippets_de_integracao/*.md
```

## Arquivos do Tigrão e função de cada um

| Arquivo | Linhas | Função identificada |
|---|---:|---|
| `app/moderation_tigrao/__init__.py` | 18 | Exporta o pacote Tigrão e documenta a ideia de painel privado. |
| `app/moderation_tigrao/actions.py` | 440 | Camada de execução real de ações Telegram: ban, mute, links, mensagens, foto, tag, reactions. |
| `app/moderation_tigrao/customize_router.py` | 181 | Callbacks e handlers para customização de grupo, especialmente foto. |
| `app/moderation_tigrao/ddx_router.py` | 254 | Painel/CRUD dos filtros DDX hard. |
| `app/moderation_tigrao/ddx_runtime.py` | 181 | Preprocessor DDX hard: detecta termos e apaga mensagem. |
| `app/moderation_tigrao/ddx_soft_router.py` | 346 | Painel/CRUD do DDX 10min e cancelamento. |
| `app/moderation_tigrao/ddx_soft_runtime.py` | 494 | Runtime do DDX 10min: agenda exclusão, notifica owner, permite cancelar. |
| `app/moderation_tigrao/inline_hmac.py` | 46 | Assinatura HMAC dos resultados inline X9. |
| `app/moderation_tigrao/inline_router.py` | 367 | Fluxo inline X9 via inline_query e chosen_inline_result. |
| `app/moderation_tigrao/keyboards.py` | 206 | Todos os botões do painel, incluindo style primary/success/danger e CopyTextButton. |
| `app/moderation_tigrao/member_tag_router.py` | 185 | Fluxo para definir tag de membro. |
| `app/moderation_tigrao/new_member_watch_router.py` | 172 | Callbacks do alerta de membro novo com link. |
| `app/moderation_tigrao/parsers.py` | 71 | Parsing de chat_id, user_id, duração e link de mensagem. |
| `app/moderation_tigrao/permissions.py` | 56 | Owner/moderador e guard de callbacks/DM. |
| `app/moderation_tigrao/pinned_media_router.py` | 129 | Recebe mídia em DM e envia/fixa no grupo selecionado. |
| `app/moderation_tigrao/pm_router.py` | 5 | Arquivo praticamente vazio no ZIP. |
| `app/moderation_tigrao/router.py` | 1451 | Painel principal, comando /tigrao, callbacks, ações, logs e reactions moderation. |
| `app/moderation_tigrao/state.py` | 161 | FSM própria por moderador usando ContextVar e sessões em memória. |
| `app/moderation_tigrao/storage.py` | 323 | Tabelas tigrao_* e funções de grupos, logs, DDX hard e DDX soft. |
| `app/moderation_tigrao/texts.py` | 26 | Textos básicos do painel. |

## Como o Tigrão funciona no ZIP

### 1. Painel principal

O painel principal fica em `router.py`. Ele abre com `/tigrao`, valida owner/moderador, cria ou reaproveita a sessão atual e responde por DM com o `home_text()` e `home_keyboard()`.

As principais seções do painel são:

- escolher grupo;
- ações de usuário;
- links;
- filtros DDX;
- mensagens;
- moderar reactions;
- personalização;
- logs;
- fechar.

### 2. FSM própria

O estado não é `aiogram.fsm`. É uma FSM manual:

- `TigrãoSession` guarda `selected_chat_id`, `selected_group_title`, `selected_action`, `waiting_for`, `payload` e `updated_at`;
- `_sessions` guarda uma sessão por moderador/owner;
- `_current_user_id` é um `ContextVar` alimentado pelo `main.py` antes de processar o update;
- timeout: 15 minutos (`SESSION_TIMEOUT`).

Isso significa que o porte mais seguro não é converter imediatamente para FSM nativo. O porte seguro é encapsular essa FSM própria em um plugin interno.

### 3. Botões coloridos e UX

`keyboards.py` cria botões com `style`:

- `primary`: navegação e ações neutras;
- `success`: confirmar/desbanir/desmutar/aprovar;
- `danger`: banir, mutar, resetar, apagar, cancelar, fechar.

Também existe botão nativo de copiar link com `CopyTextButton`.

### 4. DDX hard

O DDX hard é dividido em:

- `ddx_router.py`: menu, adicionar/remover/listar/desligar filtros;
- `ddx_runtime.py`: preprocessor que analisa mensagem antes do dispatcher, detecta palavras filtradas e apaga a mensagem.

Este é um dos pontos mais críticos para modulação, porque não é apenas painel: ele precisa rodar antes do fluxo normal do bot.

### 5. DDX soft / 10min

O DDX soft é dividido em:

- `ddx_soft_router.py`: menu, adicionar/remover/listar/desligar e cancelar exclusão agendada;
- `ddx_soft_runtime.py`: agenda exclusão futura, notifica owner e permite cancelamento por botão.

Também precisa ser hook pré-dispatch, mas pode ser ativado/desativado por flag separada.

### 6. Reactions moderation

O painel usa `reaction_audit_service` para listar reactors recentes e permitir ações como:

- apagar reaction de 1 pessoa em uma mensagem;
- apagar reactions de 1 pessoa no grupo;
- apagar todas reactions de uma mensagem;
- silenciar reactor.

Esse fluxo depende de `reaction_audit`, que é alimentado fora do pacote Tigrão, em `app/bot/telegram.py`, quando chegam updates de reaction.

### 7. New member watch

O runtime fica fora da pasta Tigrão, em `app/bot/new_member_watch_runtime.py`, mas ele é funcionalmente parte do Tigrão. Ele registra novos membros, detecta link cedo demais e notifica owner com botões `tigrao:nmw:*`. Os callbacks ficam em `app/moderation_tigrao/new_member_watch_router.py`.

### 8. Inline X9

O inline X9 fica em `inline_router.py` e `inline_hmac.py`. O bot musical também reserva no inline público o formato de dois inteiros para não conflitar com esse fluxo. Esse é outro ponto de acoplamento importante.

## Handlers e callbacks identificados

### `app/moderation_tigrao/customize_router.py`
- linha 56: `tigrao_customize_photo` — `router.callback_query(F.data == 'tigrao:customize:photo')`
- linha 80: `tigrao_receive_group_photo` — `router.message(F.photo | F.document, _is_waiting_group_photo)`
- linha 148: `tigrao_delete_photo_service_message` — `router.message(F.new_chat_photo)`

### `app/moderation_tigrao/ddx_router.py`
- linha 71: `tigrao_ddx_add` — `router.callback_query(F.data == 'tigrao:ddx:add')`
- linha 95: `tigrao_ddx_receive_add_words` — `router.message(F.text, lambda message: get_session().waiting_for == 'ddx_add_words')`
- linha 140: `tigrao_ddx_remove` — `router.callback_query(F.data == 'tigrao:ddx:remove')`
- linha 164: `tigrao_ddx_receive_remove_words` — `router.message(F.text, lambda message: get_session().waiting_for == 'ddx_remove_words')`
- linha 210: `tigrao_ddx_off` — `router.callback_query(F.data == 'tigrao:ddx:off')`
- linha 239: `tigrao_ddx_list` — `router.callback_query(F.data == 'tigrao:ddx:list')`

### `app/moderation_tigrao/ddx_soft_router.py`
- linha 82: `tigrao_ddx_soft_menu` — `router.callback_query(F.data == 'tigrao:ddx_soft:menu')`
- linha 106: `tigrao_ddx_soft_add` — `router.callback_query(F.data == 'tigrao:ddx_soft:add')`
- linha 130: `tigrao_ddx_soft_receive_add_words` — `router.message(F.text, lambda message: get_session().waiting_for == 'ddx_soft_add_words')`
- linha 178: `tigrao_ddx_soft_remove` — `router.callback_query(F.data == 'tigrao:ddx_soft:remove')`
- linha 202: `tigrao_ddx_soft_receive_remove_words` — `router.message(F.text, lambda message: get_session().waiting_for == 'ddx_soft_remove_words')`
- linha 251: `tigrao_ddx_soft_off` — `router.callback_query(F.data == 'tigrao:ddx_soft:off')`
- linha 280: `tigrao_ddx_soft_cancel` — `router.callback_query(F.data.startswith('tigrao:ddx_soft:cancel:'))`
- linha 331: `tigrao_ddx_soft_list` — `router.callback_query(F.data == 'tigrao:ddx_soft:list')`

### `app/moderation_tigrao/inline_router.py`
- linha 126: `x9_inline` — `router.inline_query()`
- linha 275: `x9_chosen` — `router.chosen_inline_result()`

### `app/moderation_tigrao/member_tag_router.py`
- linha 60: `tigrao_member_tag_start` — `router.callback_query(F.data == 'tigrao:customize:member_tag')`
- linha 84: `tigrao_member_tag_receive_text` — `router.message(F.text, _is_waiting_member_tag_text)`

### `app/moderation_tigrao/new_member_watch_router.py`
- linha 61: `tigrao_nmw_ban` — `router.callback_query(F.data.startswith('tigrao:nmw:ban:'))`
- linha 94: `tigrao_nmw_mute` — `router.callback_query(F.data.startswith('tigrao:nmw:mute:'))`
- linha 127: `tigrao_nmw_del` — `router.callback_query(F.data.startswith('tigrao:nmw:del:'))`
- linha 166: `tigrao_nmw_ignore` — `router.callback_query(F.data == 'tigrao:nmw:ignore')`

### `app/moderation_tigrao/pinned_media_router.py`
- linha 32: `tigrao_send_media_pin` — `router.callback_query(F.data == 'tigrao:message:media_pin')`
- linha 56: `tigrao_private_pinned_media` — `router.message(MEDIA_FILTER, _is_owner_waiting_pinned_media)`

### `app/moderation_tigrao/router.py`
- linha 280: `tigrao_home` — `router.message(Command('tigrao'))`
- linha 287: `tigrao_private_text` — `router.message(F.text, _is_owner_waiting_text)`
- linha 565: `tigrao_private_media` — `router.message(F.photo | F.video | F.document | F.animation | F.sticker | F.audio | F.voice | F.video_note, _is_owner_waiting_media)`
- linha 601: `tigrao_home_callback` — `router.callback_query(F.data == 'tigrao:home')`
- linha 606: `tigrao_groups` — `router.callback_query(F.data == 'tigrao:groups')`
- linha 618: `tigrao_group_manual` — `router.callback_query(F.data == 'tigrao:group:manual')`
- linha 635: `tigrao_group_select` — `router.callback_query(F.data.startswith('tigrao:group:'))`
- linha 666: `tigrao_user_actions` — `router.callback_query(F.data == 'tigrao:user_actions')`
- linha 675: `tigrao_prepare_user_action` — `router.callback_query(F.data.startswith('tigrao:action:'))`
- linha 700: `tigrao_confirm` — `router.callback_query(F.data == 'tigrao:confirm')`
- linha 774: `tigrao_cancel` — `router.callback_query(F.data == 'tigrao:cancel')`
- linha 785: `tigrao_links` — `router.callback_query(F.data == 'tigrao:links')`
- linha 790: `tigrao_create_link` — `router.callback_query(F.data.startswith('tigrao:link:'))`
- linha 839: `tigrao_messages` — `router.callback_query(F.data == 'tigrao:messages')`
- linha 844: `tigrao_customize` — `router.callback_query(F.data == 'tigrao:customize')`
- linha 856: `tigrao_customize_title` — `router.callback_query(F.data == 'tigrao:customize:title')`
- linha 877: `tigrao_customize_bio` — `router.callback_query(F.data == 'tigrao:customize:bio')`
- linha 899: `tigrao_send_text` — `router.callback_query(F.data == 'tigrao:message:send')`
- linha 920: `tigrao_send_text_pin` — `router.callback_query(F.data == 'tigrao:message:pin')`
- linha 941: `tigrao_send_media` — `router.callback_query(F.data == 'tigrao:message:media')`
- linha 962: `tigrao_delete_by_link` — `router.callback_query(F.data == 'tigrao:message:delete_link')`
- linha 979: `tigrao_ddx` — `router.callback_query(F.data == 'tigrao:ddx')`
- linha 984: `tigrao_logs` — `router.callback_query(F.data.in_({'tigrao:logs', 'tigrao:logs:refresh'}))`
- linha 990: `tigrao_rmod` — `router.callback_query(F.data == 'tigrao:rmod')`
- linha 1004: `tigrao_rmod_del_user_msg` — `router.callback_query(F.data == 'tigrao:rmod:del_user_msg')`
- linha 1021: `tigrao_rmod_del_user_chat` — `router.callback_query(F.data == 'tigrao:rmod:del_user_chat')`
- linha 1073: `tigrao_rmod_del_all_msg` — `router.callback_query(F.data == 'tigrao:rmod:del_all_msg')`
- linha 1089: `tigrao_rmod_mute_react` — `router.callback_query(F.data == 'tigrao:rmod:mute_react')`
- linha 1139: `tigrao_rmod_duration` — `router.callback_query(F.data.startswith('tigrao:rmod:dur:'))`
- linha 1165: `tigrao_rmod_pick` — `router.callback_query(F.data.startswith('tigrao:rmod:pick:'))`
- linha 1248: `tigrao_rmod_manual` — `router.callback_query(F.data.startswith('tigrao:rmod:manual'))`
- linha 1300: `tigrao_rmod_cancel` — `router.callback_query(F.data == 'tigrao:rmod:cancel')`
- linha 1314: `tigrao_rmod_confirm` — `router.callback_query(F.data == 'tigrao:rmod:confirm')`
- linha 1444: `tigrao_close` — `router.callback_query(F.data == 'tigrao:close')`


## Callback namespaces identificados

O namespace principal é `tigrao:`. Subprefixos relevantes:

- `tigrao:home`
- `tigrao:groups`
- `tigrao:group:*`
- `tigrao:action:*`
- `tigrao:link:*`
- `tigrao:message:*`
- `tigrao:customize:*`
- `tigrao:ddx:*`
- `tigrao:ddx_soft:*`
- `tigrao:rmod:*`
- `tigrao:nmw:*`
- `x9:noop`

Detalhamento por arquivo:

### `app/moderation_tigrao/customize_router.py`
- exact=['tigrao:customize:photo']
### `app/moderation_tigrao/ddx_router.py`
- exact=['tigrao:ddx:add', 'tigrao:ddx:list', 'tigrao:ddx:off', 'tigrao:ddx:remove']
### `app/moderation_tigrao/ddx_soft_router.py`
- exact=['tigrao:ddx_soft:add', 'tigrao:ddx_soft:list', 'tigrao:ddx_soft:menu', 'tigrao:ddx_soft:off', 'tigrao:ddx_soft:remove']
- startswith=['tigrao:ddx_soft:cancel:']
### `app/moderation_tigrao/ddx_soft_runtime.py`
- literais=['tigrao:ddx_soft:cancel:{chat_id}:{message_id}']
### `app/moderation_tigrao/inline_router.py`
- literais=['x9:noop']
### `app/moderation_tigrao/member_tag_router.py`
- exact=['tigrao:customize:member_tag']
### `app/moderation_tigrao/new_member_watch_router.py`
- exact=['tigrao:nmw:ignore']
- startswith=['tigrao:nmw:ban:', 'tigrao:nmw:del:', 'tigrao:nmw:mute:']
### `app/moderation_tigrao/pinned_media_router.py`
- exact=['tigrao:message:media_pin']
### `app/moderation_tigrao/router.py`
- exact=['tigrao:cancel', 'tigrao:close', 'tigrao:confirm', 'tigrao:customize', 'tigrao:customize:bio', 'tigrao:customize:title', 'tigrao:ddx', 'tigrao:group:manual', 'tigrao:groups', 'tigrao:home', 'tigrao:links', 'tigrao:message:delete_link', 'tigrao:message:media', 'tigrao:message:pin', 'tigrao:message:send', 'tigrao:messages', 'tigrao:rmod', 'tigrao:rmod:cancel', 'tigrao:rmod:confirm', 'tigrao:rmod:del_all_msg', 'tigrao:rmod:del_user_chat', 'tigrao:rmod:del_user_msg', 'tigrao:rmod:mute_react', 'tigrao:user_actions']
- startswith=['tigrao:action:', 'tigrao:group:', 'tigrao:link:', 'tigrao:rmod:dur:', 'tigrao:rmod:manual', 'tigrao:rmod:pick:']

## Pontos de acoplamento fora de `app/moderation_tigrao`

- `app/bot/music_extras.py:14` — `from app.moderation_tigrao.storage import list_groups`
- `app/bot/new_member_watch_runtime.py:30` — `from app.moderation_tigrao.permissions import is_moderator_user`
- `app/bot/new_member_watch_runtime.py:72` — `callback_data=f"tigrao:nmw:ban:{chat_id}:{user_id}",`
- `app/bot/new_member_watch_runtime.py:77` — `callback_data=f"tigrao:nmw:mute:{chat_id}:{user_id}",`
- `app/bot/new_member_watch_runtime.py:84` — `callback_data=f"tigrao:nmw:del:{chat_id}:{message_id}",`
- `app/bot/new_member_watch_runtime.py:89` — `callback_data="tigrao:nmw:ignore",`
- `app/bot/new_member_watch_runtime.py:139` — `"<b>Tigrão — membro novo postou link</b>\n\n"`
- `app/bot/new_member_watch_runtime.py:172` — `async def tigrao_new_member_watch_preprocess_update(bot, update) -> bool:`
- `app/bot/songcharts.py:17` — `from app.moderation_tigrao.permissions import is_moderator_user`
- `app/bot/songcharts.py:91` — `moderation_tigrao.member_tag_router.`
- `app/bot/telegram.py:486` — `"⚙ /tigrao\n"`
- `app/bot/telegram.py:909` — `from app.moderation_tigrao.permissions import is_owner_private_message`
- `app/bot/telegram.py:915` — `from app.moderation_tigrao.state import get_session as _tigrao_session`
- `app/bot/telegram.py:916` — `if _tigrao_session().waiting_for is not None:`
- `app/bot/tigraoresponde.py:20` — `class PendingTigraoQuestion:`
- `app/bot/tigraoresponde.py:36` — `class TigraoContinuation:`
- `app/bot/tigraoresponde.py:44` — `_pending_by_prompt: dict[tuple[int, int], PendingTigraoQuestion] = {}`
- `app/bot/tigraoresponde.py:45` — `_pending_by_relay_message_id: dict[int, PendingTigraoQuestion] = {}`
- `app/bot/tigraoresponde.py:46` — `_continuation_by_answer: dict[tuple[int, int], TigraoContinuation] = {}`
- `app/bot/tigraoresponde.py:61` — `return _command_name(text_value) == "/tigraoresponde"`
- `app/bot/tigraoresponde.py:83` — `def _find_pending_prompt(message: Message) -> PendingTigraoQuestion | None:`
- `app/bot/tigraoresponde.py:89` — `def _find_pending_relay(message: Message) -> PendingTigraoQuestion | None:`
- `app/bot/tigraoresponde.py:95` — `def _find_continuation(message: Message) -> TigraoContinuation | None:`
- `app/bot/tigraoresponde.py:101` — `async def _delete_waiting_notice(bot: Bot, pending: PendingTigraoQuestion) -> None:`
- `app/bot/tigraoresponde.py:151` — `pending = PendingTigraoQuestion(`
- `app/bot/tigraoresponde.py:170` — `async def _relay_user_question(bot: Bot, message: Message, pending: PendingTigraoQuestion) -> bool:`
- `app/bot/tigraoresponde.py:211` — `await message.reply("Apenas quem usou /tigraoresponde pode responder essa pergunta.")`
- `app/bot/tigraoresponde.py:240` — `pending = PendingTigraoQuestion(`
- `app/bot/tigraoresponde.py:267` — `_continuation_by_answer[(pending.origin_chat_id, answer_message.message_id)] = TigraoContinuation(`
- `app/btb/router.py:23` — `from app.moderation_tigrao.permissions import is_owner_callback, is_owner_private_message`
- `app/btb/router.py:24` — `from app.moderation_tigrao.storage import list_groups, remember_group`
- `app/btb/state.py:8` — `from app.moderation_tigrao.permissions import MODERATOR_IDS, OWNER_ID`
- `app/btb/state.py:26` — `# Correção do FSM (co-moderação): igual a moderation_tigrao/state.py. Os`
- `app/btb/state.py:49` — `# Bound de memória: igual a moderation_tigrao/state.py. Só persiste pra`
- `app/main.py:35` — `from app.moderation_tigrao import customize_router as tigrao_customize_router, ddx_router as tigrao_ddx_router, ddx_soft_router as tigrao_ddx_soft_router, member_tag_router as tigrao_member_tag_router, pinned_media_router as tigrao_pinned_m`
- `app/main.py:36` — `from app.moderation_tigrao.customize_router import tigrao_receive_group_photo`
- `app/main.py:37` — `from app.moderation_tigrao.ddx_router import tigrao_ddx_receive_add_words, tigrao_ddx_receive_remove_words`
- `app/main.py:38` — `from app.moderation_tigrao.ddx_runtime import tigrao_ddx_preprocess_update`
- `app/main.py:39` — `from app.moderation_tigrao.ddx_soft_runtime import tigrao_ddx_soft_preprocess_update`
- `app/main.py:40` — `from app.moderation_tigrao.new_member_watch_router import router as tigrao_new_member_watch_router  # Sprint X4`
- `app/main.py:41` — `from app.moderation_tigrao.inline_router import router as tigrao_inline_x9_router  # Sprint X9`
- `app/main.py:42` — `from app.bot.new_member_watch_runtime import tigrao_new_member_watch_preprocess_update  # Sprint X4`
- `app/main.py:43` — `from app.moderation_tigrao.keyboards import home_keyboard`
- `app/main.py:44` — `from app.moderation_tigrao.member_tag_router import tigrao_member_tag_receive_text`
- `app/main.py:45` — `from app.moderation_tigrao.permissions import is_owner_private_message`
- `app/main.py:46` — `from app.moderation_tigrao.router import tigrao_private_text`
- `app/main.py:47` — `from app.moderation_tigrao.state import get_session, set_current_user as tigrao_set_current_user`
- `app/main.py:49` — `from app.moderation_tigrao.storage import remember_group`
- `app/main.py:50` — `from app.moderation_tigrao.texts import home_text`
- `app/main.py:86` — `def _is_tigrao_command(text_value: str | None) -> bool:`
- `app/main.py:87` — `return _command_name(text_value) == "/tigrao"`
- `app/main.py:161` — `async def _handle_tigrao_direct(update: Update) -> bool:`
- `app/main.py:166` — `if not _is_tigrao_command(message.text):`
- `app/main.py:278` — `async def _handle_tigrao_waiting_text_direct(update: Update) -> bool:`
- `app/main.py:297` — `await tigrao_ddx_receive_add_words(message)`
- `app/main.py:299` — `await tigrao_ddx_receive_remove_words(message)`
- `app/main.py:301` — `await tigrao_member_tag_receive_text(message)`
- `app/main.py:303` — `await tigrao_private_text(message)`
- `app/main.py:307` — `async def _handle_tigrao_waiting_media_direct(update: Update) -> bool:`
- `app/main.py:325` — `await tigrao_receive_group_photo(message)`
- `app/main.py:363` — `dispatcher.include_router(tigrao_ddx_router)`
- `app/main.py:364` — `dispatcher.include_router(tigrao_ddx_soft_router)`
- `app/main.py:365` — `dispatcher.include_router(tigrao_customize_router)`
- `app/main.py:366` — `dispatcher.include_router(tigrao_member_tag_router)`
- `app/main.py:367` — `dispatcher.include_router(tigrao_pinned_media_router)`
- `app/main.py:368` — `dispatcher.include_router(tigrao_new_member_watch_router)  # Sprint X4`
- `app/main.py:369` — `dispatcher.include_router(tigrao_inline_x9_router)  # Sprint X9`
- `app/main.py:370` — `dispatcher.include_router(tigrao_router)`
- `app/main.py:494` — `tigrao_set_current_user(_current_uid)`
- `app/main.py:521` — `tigrao_handled = await _handle_tigrao_direct(update)`
- `app/main.py:524` — `tigrao_handled = False`
- `app/main.py:525` — `if tigrao_handled:`
- `app/main.py:556` — `tigrao_waiting_media_handled = await _handle_tigrao_waiting_media_direct(update)`
- `app/main.py:559` — `tigrao_waiting_media_handled = False`
- `app/main.py:560` — `if tigrao_waiting_media_handled:`
- `app/main.py:563` — `tigrao_waiting_text_handled = await _handle_tigrao_waiting_text_direct(update)`
- `app/main.py:566` — `tigrao_waiting_text_handled = False`
- `app/main.py:567` — `if tigrao_waiting_text_handled:`
- `app/main.py:573` — `await tigrao_new_member_watch_preprocess_update(bot, update)`
- `app/main.py:577` — `ddx_handled = await tigrao_ddx_preprocess_update(bot, update)`
- `app/main.py:586` — `await tigrao_ddx_soft_preprocess_update(bot, update)`

## Acoplamentos críticos que devem ser isolados

### A. `app/main.py`

Hoje o core importa diretamente routers, funções de waiting, preprocessadores e storage do Tigrão. Esse é o principal impedimento para plugin real.

Para isolar no mesmo bot, o `main.py` deveria conhecer apenas algo como:

```python
if settings.TIGRAO_FSM_ENABLED:
    from app.plugins.tigrao_fsm.mount import mount_tigrao_fsm
    tigrao_plugin = mount_tigrao_fsm(dispatcher)
```

E no webhook:

```python
tigrao_plugin.set_current_user_from_update(update)
if await tigrao_plugin.before_dispatch(bot, update):
    return {"ok": True}
await dispatcher.feed_update(bot, update)
```

### B. `app/bot/telegram.py`

Hoje ele precisa saber se há diálogo pendente do Tigrão para não consumir a mensagem como alias musical. O ideal é substituir por um guard genérico:

```python
if plugin_bridge.owner_dialog_active(message):
    return False
```

Também há reserva do inline X9, que deveria virar:

```python
if plugin_bridge.inline_reserved(query):
    return
```

### C. Banco

`storage.py` cria tabelas `tigrao_*` por SQL manual. Além disso, `reaction_audit` e `new_member_watch` são criadas em `database.py`. Para isolamento futuro, tudo isso deveria pertencer ao plugin, com inicialização própria:

```python
await tigrao_plugin.ensure_tables()
```

## Solução recomendada para portar o Tigrão no mesmo bot

A solução mais segura é **plugin interno com feature flags**, preservando a FSM própria e os botões coloridos.

Estrutura alvo sugerida:

```text
app/plugins/tigrao_fsm/
  __init__.py
  mount.py
  plugin.py
  router.py
  keyboards.py
  state.py
  storage.py
  actions.py
  permissions.py
  texts.py
  ddx_router.py
  ddx_runtime.py
  ddx_soft_router.py
  ddx_soft_runtime.py
  customize_router.py
  member_tag_router.py
  pinned_media_router.py
  new_member_watch_router.py
  new_member_watch_runtime.py
  inline_router.py
  inline_hmac.py
  parsers.py
```

Flags sugeridas:

```dotenv
TIGRAO_FSM_ENABLED=1
TIGRAO_FSM_PANEL_ENABLED=1
TIGRAO_FSM_DDX_ENABLED=0
TIGRAO_FSM_DDX_SOFT_ENABLED=0
TIGRAO_FSM_NEW_MEMBER_WATCH_ENABLED=0
TIGRAO_FSM_REACTIONS_ENABLED=0
TIGRAO_FSM_INLINE_X9_ENABLED=0
```

Ordem segura de ativação:

1. painel `/tigrao` abre, navega e fecha;
2. seleção de grupo;
3. logs e ações simples;
4. mensagens e personalização;
5. reactions moderation;
6. DDX hard;
7. DDX soft;
8. new member watch;
9. inline X9.

## O que não deve ser feito agora

- Não misturar `/tr4check` ou `/tr4usage` neste módulo.
- Não reescrever toda FSM para `aiogram.fsm` na primeira etapa.
- Não ativar DDX hard/soft no primeiro porte sem flag separada.
- Não deixar o bot musical importar diretamente `app.plugins.tigrao_fsm.*` em vários pontos.
- Não usar callbacks longos ou payload rico dentro do `callback_data`.

## Validações feitas para montar este pacote

- ZIP TR3 extraído com sucesso.
- 142 entradas no ZIP original.
- 20 arquivos Python encontrados em `app/moderation_tigrao`.
- `requirements.txt` lido e confirmado com `aiogram==3.27.0`.
- Referências externas ao Tigrão foram buscadas em `app/**/*.py`.
- Hash SHA256 de cada arquivo incluído foi salvo no `MANIFESTO_TIGRAO_FSM.json`.

## Limitação deste dossiê

Este pacote é uma fotografia do ZIP TR3 `0e5929e...`. Se você enviar outro ZIP ou se o TR4 atual tiver divergências, este dossiê continua útil como base, mas a aplicação real precisa comparar arquivo por arquivo antes de portar.
