# Fase 12F — comandos curtos `/t` + 3 letras em inglês

## Objetivo

Padronizar os comandos privados do TR4 com o formato autorizado:

- `/t` + três letras em inglês do que o comando faz.
- Não expor comandos de governança/moderação no escopo público de grupos.
- Manter aliases legados apenas como compatibilidade de transição.

## Mapa final

| Função | Comando principal | Aliases aceitos | Onde aparece | Onde funciona |
|---|---|---|---|---|
| Moderação privada por X9 | `/tmod` | `/mod` | Privado | Privado; no grupo só trigger silencioso |
| Configuração de grupo por DM | `/tgrp` | `/grupo` | Privado | Privado; no grupo só trigger silencioso |
| Dono global | `/town` | `/owner` | Privado | Privado do dono |
| Centro de controle owner | `/tctl` | `/show` | Privado | Privado do dono |
| Broadcast/música owner | `/tbrd` | `/broadcast` | Privado | Privado do dono |
| Adicionar regra DDX | `/tadd` | `/ddxadd` | Privado | Privado, depois de selecionar grupo |
| Remover regra DDX | `/tdel` | `/ddxdel` | Privado | Privado, depois de selecionar grupo |

## Regras preservadas

- Web App continua sendo player musical.
- X9 automático/DDX continua agindo como antes.
- X9 contextual continua alimentando o FSM privado.
- Grupo não mostra painel, botões, confirmação ou erro operacional.
- Comandos antigos continuam aceitos pelos handlers, mas não aparecem na lista privada do bot.

## Arquivos alterados

- `app/bot/setup_commands.py`
- `app/fsm_tigrao/router.py`
- `app/bot/show_owner.py`
- `app/bot/music_broadcast.py`
- `app/equalizador/router.py`
- `app/fsm_tigrao/context.py`
- `app/fsm_tigrao/x9.py`
- testes focalizados do FSM, broadcast e Owner Center

## Validação local

- `py_compile`: OK
- `validate_equalizador_embedded_html.py`: OK
- `equalizador_release_check.py`: EXIT 0 com avisos locais de ambiente
- `phase11_final_check.sh`: 99 passed, 14 skipped
- testes focais da Fase 12F: 38 passed, 4 skipped

## Decisão de compatibilidade

Aliases legados foram mantidos para evitar quebra imediata:

- `/mod`, `/grupo`, `/ddxadd`, `/ddxdel`, `/owner`, `/show`, `/broadcast`

Mas os comandos visíveis no escopo privado agora são os novos:

- `/tmod`, `/tgrp`, `/town`, `/tctl`, `/tbrd`, `/tadd`, `/tdel`
