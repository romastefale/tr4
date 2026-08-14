# RELATÓRIO DE AUDITORIA — PAINEL DE MODERAÇÃO — FASE 10

## 1. Resumo executivo

O painel de moderação do Equalizador/TR4 está **parcialmente seguro**: os endpoints principais exigem identidade (`tma` ou sessão `eqs`), bloqueiam usuários fora da lista de operadores/maestros e validam canal/permissão por palco antes de executar ações. A maior proteção real está no backend, não no botão escondido.

O maior risco encontrado é a **entrada HTML do painel por link direto**: `GET /equalizador` entrega o HTML sem autenticação e a negação acontece só no bootstrap JavaScript via `/equalizador/api/me`. Isso não permitiu comprovar execução de ações sem permissão, mas permite abrir/renderizar a casca do painel fora do fluxo Mais → Painel e aumenta dependência de JavaScript/sessionStorage para a primeira barreira.

Também há inconsistência de confirmação: o frontend exige confirmação por duplo toque apenas para ações em `criticalActions`; ações destrutivas como apagar mensagem, remover membro, revogar convite, banir canal remetente e apagar tópico não estão nesse conjunto, embora endpoints backend validem autenticação/autorização.

## 2. Base analisada

- **Repositório:** `romastefale/tr4`.
- **Branch local analisada:** `work` retornada por `git branch --show-current`. A solicitação menciona branch `main`, mas a auditoria foi feita no checkout disponível no ambiente.
- **Data da auditoria:** 2026-06-10.
- **Arquivos analisados no escopo principal:**
  - `app/equalizador/router.py`
  - `app/equalizador/admin.py`
  - `app/equalizador/seguranca_avancada.py`
  - `app/equalizador/avancado.py`
  - `app/equalizador/entradas.py`
  - `app/equalizador/painel.py`
  - `app/equalizador/mesa.py`
  - `app/equalizador/maestro.py`
  - `app/equalizador/permissions.py`
  - `app/equalizador/rbac_runtime.py`
  - `app/equalizador/hardening.py`
  - `app/equalizador/session_store.py`
- **Limitações:**
  - Não foi executado o app com Telegram real nem Bot API real.
  - Não foram feitas chamadas reais contra endpoints protegidos, para não produzir ações de moderação.
  - Não foi possível comprovar estado de variáveis de ambiente de produção, lista real de maestros/operadores, grupos reais ou direitos reais atuais do bot.
  - Onde não há evidência direta no código, está registrado como **não comprovado no código analisado**.

## 3. Caminho de entrada ideal do painel

Fluxo recomendado:

`Player público → botão Mais → Painel visível apenas para admin/autorizado → rota do painel valida sessão → bootstrap do painel valida permissão → endpoints validam novamente cada ação.`

### Situação encontrada por camada

| Camada ideal | Evidência | Cumpre? | Observação |
|---|---:|---|---|
| Player público chama backend para descobrir permissão | `public_music_me` retorna `can_open_equalizador = settings.equalizador_user_is_allowed(identity.user_id)` em `app/equalizador/router.py:8434-8458`. | Sim, parcialmente | A flag vem do backend, mas indica usuário permitido globalmente, não canal específico/palco. |
| Botão Mais → Painel só aparece para autorizado | `showMorePage()` oculta `moreAdminChoices` quando `!canOpenEqualizador` em `app/equalizador/router.py:7967`; botão `Painel` está dentro de `moreAdminChoices` em `app/equalizador/router.py:7903-7907`. | Sim, visual | Usuário comum não deveria ver o botão se `/api/public/me` retornar `false`. |
| Clique no Painel preserva sessão | `openPanel()` copia token para `sessionStorage` do painel e navega para `/equalizador` em `app/equalizador/router.py:7996`. | Sim, parcialmente | Preserva sessão local `eqs`; sem token, ainda abre HTML e falha no bootstrap. |
| Rota HTML do painel valida sessão | `equalizador_home()` retorna `_EQUALIZADOR_HTML` diretamente em `app/equalizador/router.py:5415-5425`. | Não | `GET /equalizador` não chama `_require_identity`. `/equalizador/painel` não foi encontrado como rota; deve resultar 404, mas não é o caminho usado. |
| Bootstrap valida identidade/permissão | O painel chama `/equalizador/api/me` no bootstrap em `app/equalizador/router.py:5355-5367`; `/api/me` chama `_require_identity` em `app/equalizador/router.py:5905-5908`. | Sim | Sem sessão/initData válida ou usuário não permitido, deve exibir tela negada. |
| Bootstrap valida palco/canais antes de operar | Depois de `/api/me`, chama `/api/palcos`, `/api/canais`, `/api/bot/resumo` em `app/equalizador/router.py:5377-5387`; `/api/palcos` filtra por `palco.ver` em `app/equalizador/router.py:5977-5992`. | Sim, parcialmente | O painel pode renderizar a estrutura antes dos dados, mas só mostra app após bootstrap bem-sucedido. |
| Cada endpoint valida ação novamente | `_execute_action_endpoint` valida identidade, `grp_ref`, spec e canal antes de executar em `app/equalizador/router.py:5713-5728`; há equivalentes para maestro/admin/avançado/entradas. | Sim | Esta é a principal defesa contra fetch/curl externo. |

## 4. Travas de acesso encontradas

| Camada | Arquivo/linha | Validação encontrada | Tipo | Risco | Recomendação mínima |
|---|---:|---|---|---|---|
| Botão Painel no player | `app/equalizador/router.py:7903-7907`, `7967`, `8434-8458` | `can_open_equalizador` vindo de `/api/public/me`; `moreAdminChoices` oculto se falso. | Visual + backend público | Médio: não impede URL direta. | Manter como UX, mas não tratar como segurança. |
| Sessão no player/painel | `app/equalizador/router.py:7996`, `2176-2188`, `2216-2225` | Usa `tma` quando há initData; reaproveita sessão `eqs` em storage. | Cliente | Médio: sessão antiga ainda é aceita se backend permitir grace/TTL. | Reduzir dependência de storage para entrada; validar na rota HTML ou usar redirect/401 server-side. |
| HTML `/equalizador` | `app/equalizador/router.py:5415-5425` | Nenhuma validação antes de entregar HTML. | Nenhuma/backend ausente | Alto: link direto abre casca do painel. | Proteger rota com sessão/initData quando possível ou servir shell mínimo negado sem auth. |
| Identidade geral | `app/equalizador/router.py:5428-5450`, `5462-5476` | Valida `eqs` ou Telegram initData; exige `settings.equalizador_user_is_allowed`. | Backend | Baixo/médio: depende de configuração correta. | Manter; adicionar testes de usuário comum e sessão expirada. |
| Rate limit | `app/equalizador/router.py:5467-5475` | `check_equalizador_rate_limit` por operador/bucket. | Backend | Baixo | Cobrir endpoints destrutivos em teste. |
| Palco e canal | `app/equalizador/router.py:5610-5633`, `5977-6007`, `6048-6058`, `5713-5728` | `canal_is_allowed_effective`/`filter_palco_ids_by_canal_effective`. | Backend/endpoint | Baixo/médio | Testar troca de `grp_ref` entre grupos. |
| Modo segurança | `app/equalizador/router.py:5623-5628` | Ações não read-only passam por `assert_security_action_allowed`. | Backend/endpoint | Baixo | Garantir cobertura para modo restrito. |
| Permissão real do bot | `app/equalizador/mesa.py:1191-1207`, `app/equalizador/admin.py:352-361` | Antes da chamada Telegram, verifica direito real requerido. | Backend/Telegram | Baixo | Registrar testes com bot sem direitos. |
| Logs/auditoria | `app/equalizador/router.py:5743-5767`, `7216-7252`; `app/equalizador/admin.py:362-388`; `app/equalizador/entradas.py:251-255`, `377-397` | Registra histórico/logs sanitizados na maioria das ações. | Backend | Médio: algumas rotas avançadas retornam sem log explícito no router, dependem do módulo chamado. | Padronizar log em todos os wrappers. |

## 5. Mapa botão → JS → endpoint → backend

> Observação: todos os botões `.action[data-action]` usam handler central registrado por `document.querySelectorAll("button.action[data-action]")...runAction(...)` em `app/equalizador/router.py:5300`. O mapeamento de endpoints está em `app/equalizador/router.py:2270-2312`; o payload principal é montado em `buildPayload()` em `app/equalizador/router.py:4938-5067`.

| Área | Botão visível | ID/seletor | Função JS | Endpoint/método | Payload | Backend chamado | Ação real/mock | Status da auditoria |
|---|---|---|---|---|---|---|---|---|
| Entrada | Painel | `#morePanelBtn` | `openPanel()` | `GET /equalizador` | sessão `eqs` em storage, se houver | `equalizador_home()` | Renderiza HTML | Visual protegido; rota HTML sem auth. |
| Mensagens | Enviar mensagem | `.action[data-action="mensagens.enviar"]` | `runAction` | `POST /api/palcos/{grp_ref}/mensagens/enviar` | `texto`, flags `sem_preview`, `sem_notificacao`, `fixar` | `_execute_action_endpoint` → `executar_ajuste` → `sendMessage` | Real | Autentica, autoriza canal, valida bot quando fixa. |
| Mensagens | Apagar mensagem | `.action[data-action="mensagens.apagar"]` | `runAction` | `POST /api/palcos/{grp_ref}/mensagens/apagar` | `msg_ref`, `sem_notificacao` | `_execute_action_endpoint` → `deleteMessage` | Real | Falta confirmação forte no frontend. |
| Mensagens | Apagar mensagens em lote | `#mensagens_lote_apagar` | `apagarMensagensLote()` | `POST /api/palcos/{grp_ref}/mensagens/apagar-lote` | lista de refs apagáveis | `executar_mensagens_apagar_lote` → `deleteMessages` | Real | Há bloqueio por seleção/limite; confirmação precisa ser revisada. |
| Mensagens | Fixar mensagem | `.action[data-action="fixados.criar"]` | `runAction` | `POST /api/palcos/{grp_ref}/fixados/criar` | `msg_ref`, `sem_notificacao` | `_execute_action_endpoint` → `pinChatMessage` | Real | Autorização e direito real presentes. |
| Mensagens | Remover fixado | `.action[data-action="fixados.remover"]` | `runAction` | `POST /api/palcos/{grp_ref}/fixados/remover` | `msg_ref`, `sem_notificacao` | `_execute_action_endpoint` → `unpinChatMessage` | Real | Autorização e direito real presentes. |
| Pessoas | Silenciar membro | `.action[data-action="membros.silenciar"]` | `runAction` | `POST /api/palcos/{grp_ref}/membros/silenciar` | `alvo_ref`, `duracao_segundos`, `revogar_mensagens`, `apenas_se_banido` | `_execute_action_endpoint` → `restrictChatMember` | Real | Falta confirmação forte no frontend. |
| Pessoas | Liberar membro | `.action[data-action="membros.liberar"]` | `runAction` | `POST /api/palcos/{grp_ref}/membros/liberar` | idem membros | `_execute_action_endpoint` → `restrictChatMember` | Real | OK; menos destrutiva. |
| Pessoas | Remover membro | `.action[data-action="membros.remover"]` | `runAction` | `POST /api/palcos/{grp_ref}/membros/remover` | idem membros | `_execute_action_endpoint` → `banChatMember` | Real | Falta confirmação forte no frontend. |
| Pessoas | Reintegrar membro | `.action[data-action="membros.reintegrar"]` | `runAction` | `POST /api/palcos/{grp_ref}/membros/reintegrar` | idem membros | `_execute_action_endpoint` → `unbanChatMember` | Real | OK; validar `apenas_se_banido`. |
| Convites | Criar convite | `.action[data-action="convites.criar"]` | `runAction` | `POST /api/palcos/{grp_ref}/convites/criar` | nome, expiração, limite, aprovação, enviar DM | `_execute_action_endpoint` → `createChatInviteLink` | Real | Sem confirmação; aceitável se política considerar não destrutivo. |
| Convites | Editar convite | `.action[data-action="convites.editar"]` | `runAction` | `POST /api/palcos/{grp_ref}/convites/editar` | `invite_ref`, nome, expiração, limite, aprovação | `_execute_convite_extra_endpoint` → `editChatInviteLink` | Real | Falta confirmação para alteração de acesso. |
| Convites | Revogar convite | `.action[data-action="convites.revogar"]` | `runAction` | `POST /api/palcos/{grp_ref}/convites/revogar` | `invite_ref` | `_execute_convite_extra_endpoint` → `revokeChatInviteLink` | Real | Falta confirmação forte no frontend. |
| Convites | Exportar link primário | `.action[data-action="convites.exportar_primario"]` | `runAction` | `POST /api/palcos/{grp_ref}/convites/exportar-primario` | `{}` | `_execute_convite_extra_endpoint` → export | Real/leitura operacional | Autorizado por `convites.criar`; confirmar se deve ser `convites.ver`. |
| Entradas | Aprovar entrada | `.action[data-action="entradas.aprovar"]` | `runAction` | `POST /api/palcos/{grp_ref}/entradas/aprovar` | `entrada_ref` | `_execute_entrada_endpoint` → `approveChatJoinRequest` | Real | Deveria ter confirmação leve. |
| Entradas | Recusar entrada | `.action[data-action="entradas.recusar"]` | `runAction` | `POST /api/palcos/{grp_ref}/entradas/recusar` | `entrada_ref` | `_execute_entrada_endpoint` → `declineChatJoinRequest` | Real | Deveria ter confirmação leve. |
| Pessoas | Ver admins/governantes | abas/listas | `loadPalcoData()` | `GET /api/palcos/{grp_ref}/painel`, `/governantes` | sem payload | `montar_painel_dinamico_palco`, `governantes_publicos` | Leitura real | Governantes restrito; painel dinâmico exige canal `palco.status` ou `palco.ver`. |
| Pessoas | Ver membros | abas/listas | `loadPalcoData()` | `GET /api/palcos/{grp_ref}/alvos`, `/painel` | sem payload | `list_alvos_publicos`, painel dinâmico | Leitura real | Exige canais de leitura/operação. |
| Pessoas | Ver bots | painel dinâmico | `renderPessoasPainel()` | `GET /api/palcos/{grp_ref}/painel` | sem payload | `getChatAdministrators`/dados painel | Leitura real | Depende do Bot API. |
| Histórico | Ver logs | aba Histórico | `loadPalcoData()`/`exportar_historico` | `GET /api/historico`, `GET /api/historico/exportar` | sem payload | `list_historico_publico`, `exportar_historico_publico` | Leitura real | Exportação restrita a maestro no JS; endpoint exige `historico.exportar`. |
| Reações | Limpar reação da mensagem | `.action[data-action="reacoes.mensagem.limpar"]` | `runAction` | `POST /api/palcos/{grp_ref}/reacoes/mensagem/limpar` | `msg_ref` + alvo/sender | `_execute_avancado_endpoint` → `deleteMessageReaction` | Real | Destrutiva; confirmação recomendada. |
| Reações | Limpar reações recentes | `.action[data-action="reacoes.recentes.limpar"]` | `runAction` | `POST /api/palcos/{grp_ref}/reacoes/recentes/limpar` | alvo/sender/actor | `_execute_avancado_endpoint` → `deleteAllMessageReactions` | Real | Destrutiva; confirmação recomendada. |
| Reações | Silenciar reactor | `#reacoes_silenciar_reactor` | `silenciarReactor()` | `POST /api/palcos/{grp_ref}/reacoes/reactor/silenciar` | reactor/alvo e duração | `silenciar_reactor` | Real | Endpoint autentica/autoriza. |
| Canais remetentes | Banir canal remetente | `.action[data-action="canais_remetentes.banir"]` | `runAction` | `POST /api/palcos/{grp_ref}/canais-remetentes/banir` | `sender_ref` | `_execute_avancado_endpoint` → `banChatSenderChat` | Real | Falta confirmação forte. |
| Canais remetentes | Liberar canal remetente | `.action[data-action="canais_remetentes.liberar"]` | `runAction` | `POST /api/palcos/{grp_ref}/canais-remetentes/liberar` | `sender_ref` | `_execute_avancado_endpoint` → `unbanChatSenderChat` | Real | OK. |
| Novos membros | Apagar | `#novos_apagar` | `acaoNovoMembro('apagar')` | `POST /api/palcos/{grp_ref}/novos-membros/{event_ref}/apagar` | payload de evento/duração quando aplicável | `_execute_novo_membro_endpoint` → `mensagens.apagar` | Real | Falta confirmação forte. |
| Novos membros | Silenciar | `#novos_silenciar` | `acaoNovoMembro('silenciar')` | `POST /api/palcos/{grp_ref}/novos-membros/{event_ref}/silenciar` | duração | `_execute_novo_membro_endpoint` → `membros.silenciar` | Real | Falta confirmação forte. |
| Novos membros | Banir | `#novos_banir` | `acaoNovoMembro('banir')` | `POST /api/palcos/{grp_ref}/novos-membros/{event_ref}/banir` | evento | `_execute_novo_membro_endpoint` → `membros.remover` | Real | Falta confirmação forte. |
| Novos membros | Ignorar | `#novos_ignorar` | `acaoNovoMembro('ignorar')` | `POST /api/palcos/{grp_ref}/novos-membros/{event_ref}/ignorar` | evento | marca alerta | Real local | OK. |
| Comandos críticos | Título/descrição/foto/admins/silêncio/transmissão | `.action[data-action="grupo.*"|"admins.*"|"silencio.*"|"transmissao.enviar"]` | `runAction`/`runPhotoAction` | endpoints em `grupo/*`, `admins/*`, `silencio/*`, `transmissao/enviar` | `confirmacao`, `ciente` quando crítico | `_execute_admin_endpoint`/`_execute_maestro_endpoint` | Real | Melhor camada de confirmação, inclusive backend 428. |

## 6. Problemas encontrados

| ID | Severidade | Arquivo/linha | Evidência | Causa provável | Impacto | Correção mínima recomendada | Risco de regressão | Teste recomendado |
|---|---|---:|---|---|---|---|---|---|
| P10-01 | Alta | `app/equalizador/router.py:5415-5425` | `equalizador_home()` entrega HTML sem `_require_identity`. | Painel implementado como SPA que valida no bootstrap. | Link direto abre casca do painel e expõe superfície JS/HTML. Não comprovado acesso a ações sem backend. | Validar sessão/initData na rota HTML ou servir shell negado até auth server-side. | Médio: Telegram WebApp envia initData via JS, não header em GET comum. | Abrir `/equalizador` sem sessão e verificar 401/HTML mínimo negado. |
| P10-02 | Média | `app/equalizador/router.py:2268`, `2627-2644`, `4938-5067` | `criticalActions` exclui várias ações destrutivas. | Confirmação focada em maestro/admin, não em moderação comum. | Toque acidental pode apagar/remover/revogar/banir. | Incluir destrutivas em confirmação ou confirmação contextual por tipo. | Baixo/médio: muda UX. | Testar duplo toque obrigatório para apagar, remover, revogar, banir. |
| P10-03 | Média | `app/equalizador/router.py:2176-2188`, `2216-2225`, `5432-5436` | Painel aceita sessão `eqs` salva em localStorage/sessionStorage e backend renova TTL. | Persistência para reabrir Mini App. | Sessão antiga ainda pode abrir painel até TTL/grace, inclusive navegador externo com storage. | Reduzir `grace`, invalidar ao perder permissão, associar sessão a contexto e revisar limpeza. | Médio. | Criar sessão, remover permissão do usuário, tentar `/api/me` e endpoints. |
| P10-04 | Média | `app/equalizador/router.py:6048-6058`, `5713-5728` | Bootstrap/painel valida canais; porém HTML inicial renderiza antes da autorização confirmada. | SPA client-side. | Possibilidade de “HTML abriu, JS não iniciou” ou visão inicial sem dados. | Tela inicial deve ser neutra/negada até `/api/me` OK; minimizar botões estáticos antes do bootstrap. | Baixo. | Simular JS quebrado e verificar que não há botões acionáveis visíveis. |
| P10-05 | Baixa | `app/equalizador/router.py:5211-5300` | Muitos `document.getElementById(...).addEventListener` sem guarda, embora IDs existam agora. | HTML monolítico e handlers diretos. | Remoção futura de ID quebra todo JS principal. | Padronizar helper `$safe(id)?.addEventListener` ou validação estática em CI. | Baixo. | Remover ID em teste sintético e garantir relatório estático falha. |
| P10-06 | Média | `app/equalizador/router.py:7469` | `convites.exportar_primario` usa canal `convites.criar`. | Reuso de canal operacional. | Operador com criar convite pode exportar link primário; pode ser intencional, mas não comprovado. | Revisar se deve exigir `convites.ver` ou canal específico. | Baixo. | Usuário com `convites.ver` sem `convites.criar` e inverso. |
| P10-07 | Baixa | `app/equalizador/router.py:7362-7384`, `7670-7692` | Algumas rotas avançadas não chamam `log_equalizador_event` no router; dependem do módulo. | Logs descentralizados. | Auditoria pode ficar heterogênea. | Padronizar evento OK/FAIL em wrappers ou comprovar no módulo. | Baixo/médio. | Executar ação avançada em sandbox e verificar histórico/log sanitizado. |
| P10-08 | Baixa | `app/equalizador/router.py:7387-7417`, `7722-7752` | Erros admin retornam `admin_error_public_detail`; sanitização parece existir, mas não comprovado para todo payload. | Conversão de erro por helper. | Risco residual de vazar descrição Telegram se helper falhar. | Testes unitários com erros contendo token/chat_id/user_id. | Baixo. | Injetar erro com token/chat_id e verificar resposta pública. |

## 7. Ações destrutivas e confirmações

| Ação | Destrutiva? | Confirmação frontend encontrada | Confirmação backend encontrada | Deveria exigir? |
|---|---:|---|---|---|
| Apagar mensagem | Sim | Duplo toque genérico via `armInlineConfirmation`, mas não marcada como crítica. | Não há confirmação específica; valida canal/bot. | Sim, pelo menos duplo toque contextual. |
| Apagar lote | Sim | Tem validação seleção/limite; confirmação específica não comprovada no trecho analisado. | Não há confirmação específica; valida canal/bot. | Sim, com contagem e grupo. |
| Silenciar membro | Sim | Não crítica. | Sem confirmação específica; valida canal/bot/alvo. | Sim. |
| Liberar membro | Moderada | Não crítica. | Sem confirmação específica. | Opcional. |
| Remover membro | Sim | Não crítica. | Sem confirmação específica; valida canal/bot/alvo. | Sim. |
| Reintegrar membro | Moderada | Não crítica. | Sem confirmação específica. | Opcional. |
| Fixar/desfixar | Moderada | Não crítica. | Sem confirmação específica. | Opcional. |
| Criar convite | Afeta acesso | Não crítica. | Sem confirmação específica. | Opcional/depende política. |
| Editar convite | Afeta acesso | Não crítica. | Sem confirmação específica. | Sim leve. |
| Revogar convite | Sim | Não crítica. | Sem confirmação específica. | Sim. |
| Aprovar entrada | Afeta acesso | Não crítica. | Sem confirmação específica. | Sim leve. |
| Recusar entrada | Sim para solicitante | Não crítica. | Sem confirmação específica. | Sim leve. |
| Limpar reações | Sim | Não crítica. | Sem confirmação específica. | Sim. |
| Banir canal remetente | Sim | Não crítica. | Sem confirmação específica. | Sim. |
| Novos membros: apagar/silenciar/banir | Sim | Handlers específicos; confirmação forte não comprovada. | Sem confirmação específica; delega para ações reais. | Sim. |
| Grupo título/descrição/foto/foto remover | Sim/crítica | `criticalActions` + `confirmacao` + `ciente`. | `AdminConfirmationError` quando falta confirmação. | Sim, já existe. |
| Promover/rebaixar/título admin | Crítica | `criticalActions` + `confirmacao` + `ciente`. | `AdminConfirmationError` quando falta confirmação. | Sim, já existe. |
| Modo silêncio/transmissão | Crítica | `criticalActions` + `confirmacao`. | `MaestroConfirmationError` em falha. | Sim, já existe. |

## 8. Autorização e permissões

### Permissão visual

- Player público usa `/equalizador/api/public/me` e a flag `can_open_equalizador` para mostrar/ocultar `#moreAdminChoices` e o botão `Painel`.
- No painel, navegações de maestro/segurança/configuração são condicionadas por `aplicarPerfil(me)` e por flags/canais carregados. A segurança real não deve depender disso.

### Permissão de rota

- `GET /equalizador` **não tem permissão de rota**.
- APIs chamam `_require_identity`, que valida sessão/initData e `settings.equalizador_user_is_allowed`.

### Permissão de bootstrap

- `/api/me` valida identidade e retorna operador/canais/sessão.
- `/api/palcos` filtra grupos visíveis por `palco.ver`.
- `/api/canais` exige `canais.ver` em pelo menos um palco; caso contrário retorna 403.
- `/api/palcos/{grp_ref}/painel` exige `palco.status` ou `palco.ver`.

### Permissão de endpoint

- Ações de mesa usam `ACTION_SPECS` e `_require_canal_for_palco`.
- Ações avançadas usam `ADVANCED_SPECS` e `_require_canal_for_palco`.
- Ações admin exigem `_is_maestro` e canal específico.
- Entradas/convites usam funções dedicadas com canal específico.

### Permissão real do bot no Telegram

- `executar_ajuste` chama `ensure_bot_right` antes de métodos como `deleteMessage`, `restrictChatMember`, `banChatMember`, `pinChatMessage`, `createChatInviteLink`.
- `executar_admin_critico` chama `ensure_admin_right` antes de métodos administrativos.
- Para leitura dinâmica do painel, `montar_painel_dinamico_palco` consulta Bot API para chat/admins/bot e monta ações disponíveis, mas o docstring afirma que é diagnóstico/read-only e que rotas operacionais validam novamente.

## 9. Riscos de acesso por link direto ou chamada externa

| Cenário | Resultado esperado pelo código | Risco |
|---|---|---|
| Acesso via botão Mais → Painel | Se `/api/public/me` retornar `can_open_equalizador=true`, botão aparece; clique grava sessão e navega para `/equalizador`. | Baixo/médio; caminho normal preserva sessão. |
| Link direto `/equalizador` | HTML é servido sem autenticação; JS chama `/api/me` e mostra negado se falhar. | Alto para exposição da casca; baixo para execução de ações se APIs continuarem protegidas. |
| Link direto `/equalizador/painel` | Rota não encontrada no código analisado. | Baixo; não é caminho real. |
| Navegador externo sem initData | HTML abre; `/api/me` falha se não houver sessão `eqs` salva. | Médio por dependência de storage. |
| Telegram sem initData | Mesmo comportamento; tenta sessão salva. | Médio. |
| Sessão antiga | `validate_equalizador_session` aceita token `eqs` com TTL/grace configurados. | Médio; depende de invalidação/TTL. |
| Sessão válida sem permissão global | `_require_identity` chama `settings.equalizador_user_is_allowed`; deve rejeitar 403. | Baixo se configuração atualizada. |
| Sessão válida sem canal no palco | Endpoints resolvem `grp_ref` e exigem canal por `telegram_chat_id`. | Baixo; troca de `grp_ref` deve falhar. |
| `fetch`/curl manual para endpoint | Sem Authorization → 401; sem canal → 403; sem direito bot → 403/409 conforme erro. | Baixo, desde que todos wrappers usem `_require_identity`. |
| Troca de `grp_ref` | `get_palco_internal_by_ref` resolve palco e `_require_canal_for_palco` valida canal daquele chat. | Baixo. |
| Ação destrutiva sem confirmação | Backend impede apenas críticas admin/maestro; destrutivas comuns podem executar com permissão válida. | Médio. |

## 10. Integridade HTML/JavaScript

### Verificações executadas

- Extração de `_EQUALIZADOR_HTML` via `ast.parse`.
- Extração de scripts `<script>...</script>` para `/tmp/equalizador_script_*.js`.
- `node --check` nos scripts extraídos.
- Verificação estática simples de IDs:
  - IDs no HTML: 285.
  - IDs duplicados: nenhum encontrado.
  - Referências únicas por `getElementById("...")`: 241.
  - Referências inexistentes: nenhuma encontrada.

### Achados

| Item | Resultado |
|---|---|
| `$("id").onclick` para ID inexistente | Não encontrado no painel. No player, handlers diretos existem para `#morePanelBtn` e demais botões encontrados no HTML. |
| `document.getElementById(...).addEventListener` sem guarda | Encontrado em vários pontos do painel, por exemplo `app/equalizador/router.py:5211-5300`. Hoje os IDs existem, mas a fragilidade é real. |
| IDs duplicados | Não encontrados na extração estática. |
| Botão removido mas referenciado | Não encontrado na extração estática. |
| Botão visível sem handler | Não comprovado no código analisado para botões `.action[data-action]`, pois há handler central. Botões específicos principais têm handler. |
| Handler para botão oculto permanentemente | Há botões/áreas ocultas por perfil (`moreAdminChoices`, `maestro_nav`, `seguranca_nav`, `config_nav`), mas não permanentemente; dependem de permissão. |
| Risco de “HTML abriu, mas JS principal não iniciou” | O próprio HTML tem marcação/telemetria para esse cenário no script de boot; risco permanece se um `getElementById(...).addEventListener` quebrar no início. |
| `node --check` | Passou para os scripts extraídos; porém `node --check` não pega erro de runtime por elemento nulo. |

## 11. Caminho recomendado de implementação

> Não aplicar patch nesta fase. Próximos passos pequenos recomendados:

### Fase 11 — Corrigir/fortalecer handlers e IDs

- **Arquivos prováveis:** `app/equalizador/router.py`; opcional script de validação em `scripts/` ou `tests/`.
- **Mudança:** criar validação estática de IDs e substituir handlers diretos frágeis por helper seguro onde fizer sentido.
- **Risco:** baixo.
- **Validação:** extração de HTML + `node --check` + teste de IDs inexistentes.

### Fase 12 — Reforçar entrada do painel e bootstrap

- **Arquivos prováveis:** `app/equalizador/router.py`, `app/equalizador/hardening.py`, `app/equalizador/session_store.py`.
- **Mudança:** não servir painel operacional completo em `GET /equalizador` sem sessão válida; revisar sessão antiga/grace; mostrar shell negado seguro quando sem auth.
- **Risco:** médio, porque Telegram initData normalmente nasce no JS, não em header GET.
- **Validação:** link direto sem sessão, Telegram com initData, sessão antiga, sessão revogada.

### Fase 13 — Reforçar endpoints de ações destrutivas

- **Arquivos prováveis:** `app/equalizador/router.py`, `app/equalizador/mesa.py`, `app/equalizador/entradas.py`, `app/equalizador/avancado.py`.
- **Mudança:** confirmação contextual para apagar/remover/revogar/banir/recusar/limpar; opcional token de confirmação curto.
- **Risco:** médio por UX e automações existentes.
- **Validação:** chamadas sem confirmação retornam 428; com confirmação executam.

### Fase 14 — Melhorar feedback/loading/logs

- **Arquivos prováveis:** `app/equalizador/router.py`, módulos de ação.
- **Mudança:** padronizar loading/lock para todos botões específicos; padronizar `log_equalizador_event`/histórico em wrappers avançados.
- **Risco:** baixo/médio.
- **Validação:** clique repetido, erro Bot API, histórico sanitizado.

### Fase 15 — Testes estáticos e scripts de validação

- **Arquivos prováveis:** `tests/`, `scripts/`, CI.
- **Mudança:** testes de permissão por rota, `grp_ref` trocado, user comum, sessão sem permissão, IDs e JS extraído.
- **Risco:** baixo.
- **Validação:** suíte automatizada em CI.

## 12. Checklist de validação futura

Comandos/verificações recomendadas:

- `python -m py_compile app/equalizador/router.py`
- `python -m py_compile app/equalizador/admin.py app/equalizador/seguranca_avancada.py app/equalizador/avancado.py app/equalizador/entradas.py app/equalizador/painel.py app/equalizador/mesa.py`
- Extração dos scripts JS embutidos e `node --check /tmp/equalizador_script_*.js`.
- Verificação estática de IDs HTML usados por JavaScript.
- Busca por `onclick`/`addEventListener` apontando para ID inexistente.
- Teste de `GET /equalizador` sem sessão.
- Teste de `/equalizador/api/me` sem sessão.
- Teste de `/equalizador/api/me` com sessão expirada.
- Teste de `/equalizador/api/me` com sessão válida de usuário removido das permissões.
- Teste de usuário comum tentando abrir painel pelo player público.
- Teste de admin/maestro abrindo painel pelo botão Mais.
- Teste de link direto em navegador externo sem Telegram initData.
- Teste de endpoints por curl/fetch manual sem Authorization.
- Teste de endpoints por curl/fetch com usuário permitido, mas sem canal da ação.
- Teste de endpoint com `grp_ref` inválido.
- Teste de troca de `grp_ref` para grupo onde o usuário não é admin/operador.
- Teste de bot sem `can_delete_messages` tentando apagar mensagem.
- Teste de bot sem `can_restrict_members` tentando silenciar/remover.
- Teste de ação destrutiva sem confirmação, esperando 428 após fase futura.
- Teste de resposta de erro com token/chat_id/user_id bruto injetado, garantindo sanitização.

## 13. Conclusão

O próximo patch mínimo recomendado é **Fase 12**, com proteção da entrada direta do painel e endurecimento do bootstrap, sem alterar lógica de moderação. Em paralelo ou logo depois, aplicar **Fase 13** para exigir confirmação nas ações destrutivas comuns. O código atual tem boa validação nos endpoints, mas não deve confiar na ocultação visual do botão Painel nem na entrega livre do HTML do painel.
