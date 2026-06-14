# Fase 11 — Etapa 23 — Painel do moderador limpo

## Decisão aplicada

O painel deixa de tentar funcionar como Owner Center. O `/show` fica responsável por configuração, DDX, logs, diagnóstico profundo, música automática, catálogo, bloqueios e segurança.

## Painel do moderador

O painel operacional passa a exibir somente três abas:

1. Mensagens
2. Pessoas
3. Música

A aba Música mantém apenas o envio de música atual no grupo. Rádio legado, multimídia nativa, agendamentos, catálogo e broadcast multi-grupo ficam fora do painel e devem ser operados pelo `/show` quando aplicável.

## Grupo atual

A etapa preserva o mecanismo de contexto automático criado anteriormente. Se houver grupo único, o painel abre direto; se houver ambiguidade, continua usando lista por nome/foto.

## Observação técnica

Os IDs HTML legados continuam no DOM para não quebrar handlers existentes, mas são ocultados visualmente. O carregamento operacional do painel deixa de buscar módulos owner/legados.
