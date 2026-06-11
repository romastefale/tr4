# Fase 11 — Etapa 11: broadcast automático, bloqueios musicais e resumo diário

## Objetivo

Fechar o bloco musical owner-only após a criação do `/broadcast` manual e do broadcast governante no Web App.

## Entregas

- Broadcast musical automático por horários.
- Scheduler durável com tabela `eq_music_broadcast_schedules`.
- Processamento automático a cada minuto no startup do app.
- Endpoint owner-only para processar pendências manualmente.
- Tela owner no Web App para criar, pausar, retomar e remover agendamentos.
- Bloqueio/desbloqueio global de artista/faixa por tela owner.
- Comandos owner em DM para bloqueios e agendamentos via `/broadcast`.
- Resumo diário consolidado de limites de governantes.
- Área no `/show` para consultar o estado musical e instruções rápidas.

## Regras preservadas

- Governante não escolhe destino de broadcast musical.
- Governante não fixa nem envia silencioso.
- Bloqueios de artista/faixa são globais.
- Se não houver card/canvas/capa, o broadcast não envia texto solto.
- Falha em um agendamento não derruba o scheduler.
- O owner controla a automação.

## Limitações conhecidas

- A escolha de música automática é best-effort: amostra perfis Last.fm/Spotify conhecidos e rejeita bloqueios globais.
- A seleção totalmente aleatória ponderada por todas as fontes históricas ainda pode evoluir em fase futura.
- O resumo diário consolidado é exposto no painel owner; envio automático diário por DM pode ser adicionado depois se o owner quiser horário fixo.
