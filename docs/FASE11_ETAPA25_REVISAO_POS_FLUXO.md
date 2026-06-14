# Fase 11 — Etapa 25 — Revisão pós-fluxo do painel do moderador

## Objetivo

Corrigir desalinhamentos encontrados após a Etapa 24 entre o painel simplificado, a navegação preventiva e a permissão real de broadcast musical.

## Correções

1. `broadcast.musical.webapp` agora usa `mensagens.enviar` como canal efetivo no frontend, igual ao backend.
2. Quando uma aba operacional é bloqueada preventivamente, o painel volta para `Mensagens`, não para a tela interna de resumo/diagnóstico.

## Justificativa

O painel do moderador foi definido como três abas: Mensagens, Pessoas e Música. A navegação de fallback não deve abrir telas fora dessas três abas. Além disso, o broadcast musical do moderador envia no grupo atual e depende operacionalmente da capacidade de enviar mensagem/mídia, não de um canal visual próprio chamado `broadcast.musical.webapp` na afinação do bot.
