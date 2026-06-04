# TR3 — Guia final de validação integrada

## 1. Validação local

```bash
python -m compileall app scripts tests
python scripts/smoke_imports.py
pytest
ruff check .
```

## 2. Deploy básico

- Confirmar `TR3_DATABASE_URL=sqlite:////data/app.db`.
- Confirmar diretório persistente para SQLite.
- Confirmar `TR3_TELEGRAM_BOT_TOKEN`, `TR3_BASE_URL`, `TR3_ROOT_USER_ID`.
- Subir o serviço.
- Verificar `/healthz`.
- Verificar `/readyz`.

## 3. Telegram

- Abrir privado com o bot.
- Rodar `/tigrao` como Owner.
- Abrir `/owner`.
- Selecionar grupo gerenciado.
- Entrar em Segurança.
- Rodar diagnóstico de direitos do bot.
- Confirmar que ações sem direito real aparecem indisponíveis.

## 4. Moderação por grupo

- Conceder grant mínimo, exemplo `radio.post_text`, para usuário de teste.
- Confirmar que o usuário acessa `/radio`.
- Confirmar que o usuário não acessa `/owner`.
- Confirmar que ações fora do grant ficam ocultas ou bloqueadas.
- Revogar grant e confirmar bloqueio.

## 5. Radio

- Criar template.
- Usar template como rascunho.
- Enviar texto.
- Testar pin somente se o bot tiver `can_pin_messages`.
- Criar agendamento pequeno em grupo de teste.
- Confirmar anti-duplicação e histórico.
- Testar broadcast em conjunto restrito de grupos.

## 6. Locks e operações críticas

- Rodar broadcast e confirmar operação crítica registrada.
- Trocar security mode e confirmar auditoria.
- Fazer ação de governança em grupo de teste e confirmar intenção/resultado.
- Confirmar painel `Operações críticas`.

## 7. Exportação/auditoria

- Exportar auditoria JSONL.
- Exportar operações JSONL.
- Exportar `.jsonl.gz` assinado com manifesto.
- Configurar `TR3_AUDIT_EXPORT_ENCRYPTION_KEY`.
- Exportar `.enc`.
- Confirmar manifesto sem segredo.
- Confirmar `key_id` em manifesto.

## 8. Segurança final

- Confirmar que `/owner` digitado por não-Owner é bloqueado.
- Confirmar que callback forjado não executa ação sem permissão.
- Confirmar panic mode `restricted` bloqueia delegados.
- Confirmar modo `normal` restaura operação.

## Critério de aceite

O release candidate só deve ser promovido se:

- Todos os testes locais passarem.
- `/readyz` responder `ready` após startup.
- Owner conseguir reverter panic/restricted.
- Delegado não acessar governança.
- Broadcast delegado ficar limitado aos grupos com grant.
- Export criptografado não gravar chave em logs/manifesto.
