# Fase 54.3 — Mensagens e fixação

Esta fase reorganiza e completa a janela **Mensagens** do Equalizador, mantendo a base da Fase 54.2.

## Escopo

- Adiciona envio de mensagem diretamente pela janela Mensagens.
- Permite enviar sem prévia de links.
- Permite enviar sem notificação.
- Permite enviar e fixar depois do envio.
- Registra a mensagem enviada como referência interna `msg_...`.
- Mantém apagar, fixar mensagem existente, remover fixado e resolver link de mensagem na mesma janela.
- Não expõe ID numérico real de mensagem ou grupo na interface.

## Segurança operacional

O canal `mensagens.enviar` autoriza apenas o envio da mensagem. Se o operador marcar “fixar depois do envio”, o backend exige também o canal `fixados.criar` antes de executar a fixação.

A fixação continua dependente do direito real do bot `can_pin_messages` no Telegram.

## Validação local

```bash
python -m compileall -q app scripts tests
PYTHONPATH=. pytest -q
PYTHONPATH=. python scripts/equalizador_release_check.py
```

Resultado obtido no sandbox:

```text
84 passed, 18 skipped
```

O `equalizador_release_check.py` retornou apenas avisos esperados por falta de token/domínio público no sandbox.
