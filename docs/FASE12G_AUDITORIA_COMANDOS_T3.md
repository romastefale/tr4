# Fase 12G — auditoria final dos comandos T3

## Veredito

A Fase 12F estava correta na separação de escopos, mas a auditoria encontrou uma falha funcional crítica no comando DDX novo:

- `/tadd` era roteado para o handler correto, mas a lógica interna só tratava `ddxadd` como adição.
- Como consequência, `/tadd palavra` cairia no ramo de remoção.
- `/tdel` e `/ddxdel` ficavam coerentes por acidente, porque tudo que não era `ddxadd` removia.

A Fase 12G corrige isso e adiciona teste para impedir regressão.

## Correção aplicada

Arquivo: `app/fsm_tigrao/router.py`

Antes:

```python
if command == "ddxadd":
    ... adiciona ...
else:
    ... remove ...
```

Depois:

```python
if command in {"tadd", "ddxadd"}:
    ... adiciona ...
elif command in {"tdel", "ddxdel"}:
    ... remove ...
else:
    ... comando inválido ...
```

## Teste novo

Arquivo: `tests/test_fase12g_t_commands_audit.py`

Coberturas:

1. `/tadd` e `/ddxadd` entram no ramo de adicionar.
2. `/tdel` e `/ddxdel` entram no ramo de remover.
3. Comandos T3 continuam somente no escopo privado do menu.
4. Aliases antigos continuam como aliases de handler, mas não aparecem no menu.
5. `/tmod`, `/tgrp`, `/tadd` e `/tdel` no grupo continuam silenciosos.

## Conferência de escopo

Comandos principais visíveis no privado:

- `/tmod` — moderação manual via DM/X9.
- `/tgrp` — configuração de grupo via DM.
- `/town` — dono global.
- `/tctl` — centro owner.
- `/tbrd` — broadcast/música owner.
- `/tadd` — adicionar DDX via DM.
- `/tdel` — remover DDX via DM.

Aliases antigos aceitos por compatibilidade, mas não expostos no menu:

- `/mod`
- `/grupo`
- `/owner`
- `/show`
- `/broadcast`
- `/ddxadd`
- `/ddxdel`

## Regra final preservada

- Web App = player musical.
- X9 automático/DDX = continua agindo.
- X9 contextual = alimenta o privado.
- FSM privado = decide ações manuais.
- Grupo = sem painel, sem botões, sem confirmação, sem erro operacional.

## Base oficial consultada

A documentação do Telegram confirma que comandos de bot têm 1 a 32 caracteres e podem conter letras minúsculas em inglês, dígitos e underscores. Também confirma escopos de comandos para chats privados, grupos e administradores. A configuração de escopo melhora UX, mas não substitui validação backend.

A documentação também confirma que `deleteMessage` tem limitações operacionais, incluindo janela de 48 horas; por isso a retenção operacional do X9 deve continuar curta.

## Validação local

- `py_compile`: OK
- `validate_equalizador_embedded_html.py`: OK
- `equalizador_release_check.py`: EXIT 0 com avisos locais de ambiente
- pytest focal: 17 passed, 1 skipped
- `phase11_final_check.sh`: 99 passed, 14 skipped

## Recomendação

A Fase 12G substitui a 12F como pacote recomendado para aplicação real.
