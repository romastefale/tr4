# Fase 11 — Etapa 10 — FSM owner e editor visual de pacotes

## Objetivo

Fechar o controle manual do owner antes da automação musical. Esta etapa adiciona configuração por botões no `/show` e um editor visual no Web App owner para pacotes governante, pacote personalizado, limites e exceções de 24h.

## Entregue

- `/show` continua restrito à DM do owner/maestro.
- `/show` agora usa botões para escolher grupo, governante, pacote, pacote personalizado, limites e exceções.
- Pacote personalizado pode ser montado por marcação de ações, sem payload manual.
- Limites diários podem ser definidos por botões no `/show`.
- Exceção de 24h pode ser criada/cancelada pelo `/show`.
- Configuração do owner no Web App recebeu editor visual de pacote governante.
- O editor visual usa os endpoints owner-only já existentes:
  - `POST /equalizador/api/governantes/pacotes`
  - `DELETE /equalizador/api/governantes/pacotes/{assignment_ref}`
  - `POST /equalizador/api/governantes/pacotes/{assignment_ref}/limites`
  - `POST /equalizador/api/governantes/pacotes/{assignment_ref}/excecoes`
  - `DELETE /equalizador/api/governantes/excecoes/{exception_ref}`

## Fora desta etapa

- Broadcast musical automático por horários.
- Bloqueio/desbloqueio de artista/faixa.
- Resumo diário consolidado.

Esses itens ficam para a Etapa 11.
