# TR3 — Release Candidate Final após Fase 10N

Data: 2026-06-04

## Status

Este pacote consolida o trabalho das fases 8 a 10N como **release candidate**.

Não foram alteradas regras de permissão nesta consolidação. O objetivo foi reunir documentação final, checklist de validação e template de variáveis.

## Principais capacidades consolidadas

- SQLite-only com validação de URL de banco.
- Painel `/tigrao` como entrada modular.
- Painel `/owner` separado para Owner.
- Painel `/radio` separado para postagens, templates, histórico, agendamento e broadcast.
- Permissões por grupo para moderação e `radio.*`.
- Broadcast limitado por grants e grupos gerenciados.
- Panic/security mode, monitoramento e alertas.
- Rate limit.
- Direitos reais do bot refletidos nos botões.
- Sessão privada isolada por usuário com persistência leve.
- Locks operacionais SQLite para scheduler e ações críticas.
- Auditoria crítica com registro de intenção/resultado.
- Export JSONL, JSONL.GZ, manifesto SHA-256 e export criptografado opcional AES-256-GCM.
- `key_id` e keyring para rotação de chaves de export criptografado.
- `/healthz` e `/readyz`.

## Pontos que continuam intencionais

- Menu nativo do Telegram é UX, não autorização.
- Botões indisponíveis são UX; handlers continuam validando permissões/capacidades.
- Export criptografado depende de `TR3_AUDIT_EXPORT_ENCRYPTION_KEY` configurada.
- Replay de operações críticas é informativo/manual, não automático.
- Em grupos onde o bot não é admin, operação deve permanecer musical-only.

## Validação exigida fora desta sandbox

Rode em ambiente com dependências completas:

```bash
python -m compileall app scripts tests
python scripts/smoke_imports.py
pytest
ruff check .
```

Depois valide manualmente os painéis no Telegram conforme `TR3_FINAL_VALIDATION_GUIDE.md`.
