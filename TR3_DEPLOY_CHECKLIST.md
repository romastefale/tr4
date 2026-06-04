# TR3 — Checklist de validação antes do deploy

## 1. Código

- [ ] Usar o ZIP final da Fase 8 como base.
- [ ] Confirmar que não há `__pycache__`, `.pyc`, `.pyo` no pacote.
- [ ] Rodar `python -m compileall app scripts tests` no ambiente com dependências.
- [ ] Rodar `python scripts/smoke_imports.py`.
- [ ] Rodar `pytest`.

## 2. Banco

- [ ] Confirmar `TR3_DATABASE_URL=sqlite:////data/app.db` ou equivalente.
- [ ] Confirmar que `/data` ou diretório escolhido é persistente.
- [ ] Confirmar permissão de escrita no diretório do SQLite.

## 3. Webhook

- [ ] Confirmar `TR3_BASE_URL=https://...`.
- [ ] Confirmar que `/webhook` está acessível apenas via Telegram com secret token.
- [ ] Verificar `/healthz`.

## 4. Grupos

- [ ] Adicionar grupos em `TR3_MANAGED_GROUP_IDS`.
- [ ] Tornar o bot admin apenas nos grupos que devem ter moderação.
- [ ] Sem admin, validar que comandos musicais continuam funcionando.
- [ ] Em grupo gerenciado com admin, validar DDX/delete com `can_delete_messages`.
- [ ] Validar ban/mute apenas se o bot tiver `can_restrict_members`.

## 5. Permissões Telegram recomendadas

Para moderação forte sem governança estrutural:

- [ ] `can_delete_messages`
- [ ] `can_restrict_members`
- [ ] `can_pin_messages`, se usar pins
- [ ] `can_manage_tags`, se usar tags

Owner-only/estrutural, só se realmente for usar pelo bot:

- [ ] `can_change_info`
- [ ] `can_invite_users`
- [ ] `can_manage_topics`
- [ ] `can_promote_members`, extrema cautela

## 6. Painel

- [ ] Abrir `/tigrao` no privado.
- [ ] Confirmar painel principal.
- [ ] Confirmar seção Moderadores só para Owner.
- [ ] Conceder grant de teste para usuário em grupo gerenciado.
- [ ] Confirmar que delegado não acessa Governança.
- [ ] Confirmar que Governança exige confirmação dupla.

## 7. Segurança

- [ ] Abrir painel Segurança.
- [ ] Executar check manual.
- [ ] Testar modo `alert`.
- [ ] Testar modo `restricted`.
- [ ] Confirmar que Owner consegue voltar para `normal`.
- [ ] Confirmar que delegados são bloqueados no restricted.

## 8. Rate limit

- [ ] Testar comando caro repetidamente.
- [ ] Confirmar bloqueio amigável.
- [ ] Confirmar que não afeta comandos básicos indevidamente.

## 9. Logs/auditoria

- [ ] Confirmar eventos `grant`/`revoke` em `audit_events`.
- [ ] Confirmar eventos de governança em `audit_events`.
- [ ] Confirmar alertas no chat configurado.


## 10. Radio agendado

- [ ] Criar um template de teste no `/radio`.
- [ ] Criar agendamento para grupo gerenciado de teste.
- [ ] Configurar janela de silêncio e validar que posts agendados são pulados.
- [ ] Testar broadcast por template em grupos gerenciados pequenos.
- [ ] Confirmar histórico `radio_post_history`.
- [ ] Confirmar que duplicidade recente é bloqueada.


## 11. Radio delegável

- [ ] Conceder `radio.post_text` a um usuário em grupo de teste.
- [ ] Confirmar que o usuário abre `/radio`.
- [ ] Confirmar que o usuário só posta no grupo onde tem grant.
- [ ] Conceder `radio.pin` e validar postagem fixada.
- [ ] Conceder `radio.templates.use` e validar uso de template como rascunho.
- [ ] Confirmar que sem `radio.broadcast` o usuário não consegue broadcast.
- [ ] Confirmar que com `radio.broadcast` o broadcast fica restrito aos grupos com esse grant.


## 12. Radio qualidade operacional

- [ ] Abrir `/radio` como Owner e confirmar que todos os botões aparecem.
- [ ] Abrir `/radio` como delegado sem grupo selecionado e confirmar que só aparece Escolher grupo.
- [ ] Selecionar grupo com `radio.post_text` e confirmar que só aparece Enviar mensagem.
- [ ] Testar paginação de Templates.
- [ ] Testar paginação de Histórico.
- [ ] Testar paginação de Agendamentos.
- [ ] Clicar callback antigo/malformado e confirmar bloqueio sem exceção.


## 13. Qualidade operacional global

- [ ] Verificar `/healthz`.
- [ ] Verificar `/readyz` após startup.
- [ ] Confirmar que `/readyz` retorna 503 em ambiente incompleto.
- [ ] Confirmar logs `AIOGRAM_ERROR_HANDLED` se houver exceção de dispatcher.
- [ ] Rodar `python -m compileall app scripts tests`.
- [ ] Rodar `python scripts/smoke_imports.py`.
- [ ] Rodar `pytest`.
- [ ] Rodar `ruff check .` se ruff estiver instalado.


## 14. Comandos por escopo

- [ ] Confirmar que o menu `/` público não mostra `/owner`, `/tigrao` ou `/radio`.
- [ ] Confirmar que o privado do Owner mostra `/tigrao`, `/owner` e `/radio`.
- [ ] Confirmar que moderador legado não vê `/owner`.
- [ ] Confirmar que grupos mostram apenas comandos musicais/públicos.
- [ ] Confirmar que acesso real continua controlado por RBAC, não pelo menu nativo.


## 15. Sincronização dinâmica de comandos

- [ ] Conceder `radio.post_text` para usuário de teste.
- [ ] Confirmar que o menu privado desse usuário passa a sugerir `/radio`.
- [ ] Revogar permissões do usuário.
- [ ] Confirmar que o menu privado volta a comandos públicos.
- [ ] Confirmar que falha de menu não desfaz grant/revoke.
- [ ] Confirmar auditoria `commands/sync_after_grant` ou `commands/sync_after_revoke`.


## 16. Resync administrativo de comandos

- [ ] Abrir `/owner`.
- [ ] Entrar em Segurança.
- [ ] Usar `Ressincronizar menus`.
- [ ] Confirmar resposta com Total/Sucesso/Falhas.
- [ ] Confirmar auditoria `commands/resync_active_grants`.
- [ ] Confirmar que permissões não mudam quando o menu falha.


## 17. Direitos reais nos botões

- [ ] Selecionar grupo onde o bot não é admin.
- [ ] Confirmar que ações administrativas aparecem indisponíveis.
- [ ] Selecionar grupo onde o bot não tem `can_pin_messages`.
- [ ] Confirmar que botões de fixar aparecem indisponíveis.
- [ ] Selecionar grupo onde o bot não tem `can_delete_messages`.
- [ ] Confirmar que apagar mensagem/reactions aparece indisponível.
- [ ] Confirmar que clicar em botão indisponível mostra alerta explicativo.
- [ ] Confirmar que handlers ainda bloqueiam execução mesmo se callback for forjado.


## 18. Diagnóstico de direitos do bot

- [ ] Abrir `/owner`.
- [ ] Selecionar um grupo.
- [ ] Entrar em Segurança.
- [ ] Usar `Atualizar direitos do grupo`.
- [ ] Confirmar linha com capacidades do grupo selecionado.
- [ ] Usar `Diagnóstico direitos todos`.
- [ ] Confirmar resumo Total/Admin/Musical-only/Erro.
- [ ] Confirmar auditoria `bot_rights/refresh_selected`.
- [ ] Confirmar auditoria `bot_rights/refresh_managed_groups`.
- [ ] Confirmar que grants/RBAC não mudam.


## 19. Hardening de sessão privada

- [ ] Abrir `/owner` como Owner.
- [ ] Abrir `/radio` como delegado simultaneamente.
- [ ] Selecionar grupos diferentes e confirmar isolamento.
- [ ] Entrar em Segurança.
- [ ] Usar `Diagnóstico sessões`.
- [ ] Confirmar que não aparecem valores sensíveis de payload.
- [ ] Usar `Limpar sessões expiradas`.
- [ ] Confirmar auditoria `sessions/diagnostics` e `sessions/cleanup_expired`.

## 19. Sessões persistentes e locks operacionais

- [ ] Confirmar criação das tabelas `private_sessions` e `operational_locks`.
- [ ] Abrir painel, selecionar grupo e reiniciar processo.
- [ ] Confirmar que a sessão do usuário autorizado é recuperada.
- [ ] Rodar scheduler Radio com duas réplicas e confirmar apenas uma execução por lock.
- [ ] Abrir Segurança → Sessões persistidas.
- [ ] Abrir Segurança → Locks operacionais.
- [ ] Usar Limpar locks expirados.
- [ ] Confirmar que locks/sessões não alteram grants RBAC.


## 19. Locks por ação crítica

- [ ] Iniciar duas instâncias usando o mesmo SQLite.
- [ ] Disparar broadcast simultâneo e confirmar que uma execução fica bloqueada.
- [ ] Alterar modo de segurança simultaneamente e confirmar bloqueio de concorrência.
- [ ] Executar governança estrutural simultânea no mesmo grupo e confirmar lock.
- [ ] Confirmar auditoria `radio/broadcast_lock_busy`, `security/mode_change_lock_busy` ou `governance` com status `blocked`.
- [ ] Confirmar limpeza de locks expirados no painel Segurança.


## 19. Auditoria de operações críticas

- [ ] Executar broadcast de teste e confirmar registro em `critical_operations`.
- [ ] Alterar security mode e confirmar operação crítica.
- [ ] Executar governança em grupo de teste e confirmar intenção/resultado.
- [ ] Abrir Segurança -> Operações críticas.
- [ ] Confirmar que pacote de replay não executa ação automaticamente.
- [ ] Confirmar que operação com lock ocupado fica `blocked`.


## 20. Retenção/exportação de auditoria

- [ ] Abrir `/owner`.
- [ ] Entrar em Segurança.
- [ ] Usar `Exportar auditoria`.
- [ ] Confirmar arquivo JSONL de `audit_events`.
- [ ] Usar `Exportar operações`.
- [ ] Confirmar arquivo JSONL de `critical_operations`.
- [ ] Usar `Limpar auditoria antiga`.
- [ ] Confirmar tela de confirmação.
- [ ] Confirmar auditoria `audit_retention/cleanup_old_records`.
- [ ] Confirmar que grants/RBAC não mudaram.


## 19. Export assinado e compactado

- [ ] Abrir `/owner`.
- [ ] Entrar em Segurança.
- [ ] Usar `Exportar auditoria .gz`.
- [ ] Confirmar recebimento de `.jsonl.gz` e `.manifest.json`.
- [ ] Conferir `gzip_sha256` do manifesto contra o arquivo `.gz`.
- [ ] Usar `Exportar operações .gz`.
- [ ] Confirmar auditoria `audit_export/export_audit_events_signed`.
- [ ] Confirmar auditoria `audit_export/export_critical_operations_signed`.


## 20. Backup criptografado opcional

- [ ] Definir `TR3_AUDIT_EXPORT_ENCRYPTION_KEY` em ambiente seguro.
- [ ] Testar `Exportar auditoria .enc`.
- [ ] Testar `Exportar operações .enc`.
- [ ] Confirmar envio de `.jsonl.gz.enc` e `.manifest.json`.
- [ ] Confirmar que manifesto não contém a chave.
- [ ] Guardar a chave fora do Telegram e do repositório.
- [ ] Testar recuperação manual em ambiente seguro antes de depender do backup.


## 19. Rotação de chaves de export criptografado

- [ ] Definir `TR3_AUDIT_EXPORT_ENCRYPTION_KEY_ID`.
- [ ] Gerar export criptografado e conferir `key_id` no manifesto.
- [ ] Mover chave antiga para `TR3_AUDIT_EXPORT_DECRYPTION_KEYS` antes de trocar a chave atual.
- [ ] Testar decrypt offline de export antigo com keyring.
- [ ] Testar decrypt offline de export novo com chave atual.
- [ ] Confirmar que nenhum manifesto contém segredo real.
- [ ] Registrar rotação em controle operacional externo.
