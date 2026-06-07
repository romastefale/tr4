# Fase 55.5 — Radio: agendamento, silêncio e broadcast

Esta fase consolida três funções do Radio que existiam no TR3 em fluxos de FSM e passam a existir no Equalizador como janelas do Mini App.

## Funções adicionadas

- Agendamento de publicação de texto ou modelo.
- Processamento automático de agendamentos vencidos por tarefa de fundo a cada 60 segundos.
- Processamento manual de agendamentos vencidos pelo painel, restrito ao administrador principal.
- Janela de silêncio operacional por grupo.
- Broadcast multi-grupo respeitando os canais do operador.
- Registro das publicações no histórico próprio do Radio.

## Canais novos

- `radio.agendar`
- `radio.quiet`
- `radio.broadcast`

A regra de execução continua em três camadas: canal concedido ao operador, permissão real do bot quando a ação atinge o Telegram, e tratamento sanitizado de erro.

## Limites intencionais

O agendamento desta fase publica texto ou modelo. Mídia continua pelo rascunho seguro manual, porque persistir mídia agendada em base64 aumentaria o peso do banco e do iPhone. Broadcast também é texto/modelo e limita a execução a 25 grupos por operação.
