# Fase 12B — FSM privado + X9 silencioso

## Regra de produto corrigida

O grupo não deve mostrar menu de ação, botões de moderação, erros ou confirmações. O grupo serve apenas como fonte de contexto operacional quando inevitável. A decisão e o retorno ficam no privado do bot.

## Separação final

- Web App: player musical.
- Grupo: X9 silencioso; captura mensagens, autores e grupos conhecidos.
- Privado do bot: `/tmod`, `/tgrp`, `/tadd`, `/tdel`.
- Dono do código: `/town` e `/tctl` em DM.

## Comportamento dos comandos

### `/tmod`

No grupo: captura silenciosamente o contexto e tenta apagar o trigger. Não envia menu no grupo.

No privado: lista grupos observados pelo X9, mostra mensagens recentes e permite agir por botões com confirmação privada.

Ações iniciais:

- apagar mensagem;
- fixar mensagem;
- banir autor quando o autor foi observado com segurança;
- silenciar autor por 1 hora quando o autor foi observado com segurança.

### `/tgrp`

No grupo: captura silenciosamente o contexto e tenta apagar o trigger. Não envia menu no grupo.

No privado: lista grupos observados e permite status do bot, convite com aprovação e DDX.

### `/tadd` e `/tdel`

No grupo: não configuram nada visível; apenas passam pelo capturador silencioso.

No privado: alteram o DDX do grupo selecionado na sessão privada.

## X9

`app/fsm_tigrao/x9.py` registra contexto de updates de grupo antes do dispatcher. O capturador não responde no grupo e não bloqueia os handlers musicais/tmoderação existentes.

## Comandos públicos

`/tmod`, `/tgrp`, `/tadd` e `/tdel` foram removidos do escopo público de comandos. Eles ficam no escopo privado. Mesmo se alguém digitar no grupo, o handler não mostra painel.

## Limites conscientes

O bot só consegue enviar DM para quem já iniciou conversa privada com ele. Se um moderador nunca abriu o bot, o trigger de grupo pode ser capturado, mas a orientação privada pode falhar silenciosamente por regra do Telegram.
