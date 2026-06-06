# Fase 60 — Auditoria final de estabilização do Equalizador

Esta fase não adiciona funcionalidade nova. O objetivo é fechar a sequência 56–59 com uma revisão objetiva do pacote aplicado, validando que as melhorias de concorrência, sessão, DDX persistente, apagamento em lote, UX preventiva e erros estruturados permanecem integradas ao TR4 real.

## Escopo validado

1. **SQLite e sessão**: a configuração real de `app/db/database.py` mantém `DATABASE_URL`, criação de diretório, `check_same_thread=False`, `timeout=10.0`, `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=10000` e `PRAGMA synchronous=NORMAL`.
2. **DDX persistente**: o worker usa a tabela existente `eq_ddx_soft_pending`, sem criar tabela paralela genérica. A tarefa `_ddx_scheduler_loop()` é iniciada no startup quando o Equalizador e o token do bot estão configurados.
3. **Apagamento em lote**: o endpoint `/equalizador/api/palcos/{grp_ref}/mensagens/apagar-lote` recebe somente `msg_refs`, resolve IDs reais no servidor e executa `deleteMessages` com limite de até 100 mensagens.
4. **Interface preventiva**: o Mini App bloqueia ações e janelas quando falta canal concedido ao operador ou direito real do bot, reduzindo cliques que terminariam em `403`, `409` ou erro de estado previsível.
5. **Erros Telegram**: a Mesa preserva payload estruturado e sanitizado, com categorias públicas como `bot_lacks_permissions`, `target_not_admin`, `target_already_admin`, `target_is_creator`, `rate_limit`, `bad_request`, `conflict` e `telegram_unavailable`.
6. **Shutdown**: `shutdown_telegram_bot()` cobre Spotify, Last.fm, cápsula Last.fm e lyrics, evitando deixar pools HTTP abertos no encerramento da aplicação.

## Fontes técnicas verificadas

- Telegram Bot API: `deleteMessages` aceita lista de 1 a 100 mensagens e usa as limitações de `deleteMessage`.
- Telegram Bot API: `deleteMessage` tem limite geral de 48 horas e exige permissões reais conforme o tipo de chat.
- aiogram 3: exceções específicas do v2 foram consolidadas em classes como `TelegramBadRequest`, `TelegramNotFound`, `TelegramForbiddenError`, `TelegramConflictError` e `TelegramRetryAfter`, justificando classificação por payload/categoria sanitizada.
- FastAPI: `lifespan` é o caminho recomendado, mas misturar `lifespan` com handlers `startup/shutdown` desativa os eventos antigos; por isso esta sequência preserva os eventos existentes e reforça o shutdown no ponto real do projeto.
- SQLite: `PRAGMA` e WAL são mecanismos oficiais do SQLite; o projeto aplica os PRAGMAs apenas em conexão SQLite.

## Validação local executada nesta fase

```bash
python -m compileall -q app scripts tests
python scripts/equalizador_phase60_audit.py
python -m pytest -q tests/test_equalizador_phase60_auditoria.py
node --check /mnt/data/equalizador_phase60_script_1.js
python scripts/equalizador_release_check.py
```

Observação: `scripts/smoke_imports.py` depende de `aiogram`. No ambiente de análise usado para esta auditoria, `aiogram` não está instalado, então esse smoke não é conclusivo fora do ambiente de dependências completo do projeto.

## Conclusão

As fases 58 e 59 foram mantidas como correção funcional; a fase 60 confirma a integração, adiciona teste/auditoria estática e documenta o estado final sem alterar arquitetura sensível nem acrescentar novas features.
