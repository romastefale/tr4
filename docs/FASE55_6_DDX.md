# Fase 55.6 — DDX imediato e DDX 10 minutos

Esta fase reimplanta no Equalizador os filtros DDX que existiam no TR3, exceto o fluxo privado antigo por FSM. A configuração passa a ficar em janela própria do Mini App.

## Funções adicionadas

- Janela **Filtros** no Equalizador.
- DDX imediato: apaga a mensagem assim que uma palavra/frase configurada for detectada.
- DDX 10 minutos: agenda o apagamento para 10 minutos depois.
- Cancelamento de apagamento DDX 10 minutos enquanto ainda estiver pendente.
- Histórico sanitizado de eventos DDX.
- Notificação privada para administradores principais quando uma ação automática é executada.

## Canais novos

- `ddx.imediato`
- `ddx.temporario`

Ambos dependem de direito real do bot para apagar mensagens (`can_delete_messages`).

## Privacidade

A interface não exibe ID real de grupo, mensagem ou usuário. Eventos mostram nome público, @username quando disponível, palavras acionadas e prévia sanitizada da mensagem.

## Observação operacional

O DDX 10 minutos usa tarefa em memória para o apagamento futuro. Se o serviço reiniciar antes de completar os 10 minutos, o evento pendente permanece no banco como registro, mas a tarefa em memória não continua. Essa decisão preserva compatibilidade com o comportamento aceito no TR3 para filtros temporários.
