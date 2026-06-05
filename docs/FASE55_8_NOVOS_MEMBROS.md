# Fase 55.8 — Monitor de novos membros com link

Esta fase reimplanta no Equalizador o monitor de recém-chegados com link, sem trazer o módulo antigo como cópia.

## Escopo

- Observa eventos de entrada de novos membros nos grupos autorizados.
- Mantém uma janela curta de acompanhamento do recém-chegado.
- Detecta links nas primeiras mensagens.
- Registra alerta sanitizado no painel.
- Notifica os administradores principais em privado quando possível.
- Permite agir pelo Mini App: apagar mensagem, silenciar, banir ou ignorar alerta.

## Privacidade

A interface não mostra IDs reais. O painel usa `alvo_ref`, `msg_ref` e `event_ref` internos. Quando disponíveis, mostra nome público e `@username` com link público.

## Canais novos

- `novos.ver`
- `novos.apagar`
- `novos.silenciar`
- `novos.banir`
- `novos.ignorar`

## Direitos reais do bot

- Apagar mensagem exige `can_delete_messages`.
- Silenciar ou banir exige `can_restrict_members`.
- O monitor só atua em grupos configurados em `TR4_EQUALIZADOR_PALCO_IDS`.

## Observação operacional

O watcher depende de updates de mensagem do Telegram. A entrada do membro cria a janela de observação; o alerta é criado somente se esse recém-chegado enviar link dentro da janela curta.
