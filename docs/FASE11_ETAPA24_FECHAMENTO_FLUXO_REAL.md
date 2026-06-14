# Fase 11 — Etapa 24 — Fechamento de fluxo real

Esta etapa corrige os buracos de fluxo encontrados no estudo pós-Etapa 23.

## Correções principais

- Convite rápido foi colocado dentro da aba Pessoas, mantendo o painel do moderador com apenas Mensagens, Pessoas e Música.
- O painel passa a renderizar cartões de grupo por nome/foto quando o contexto automático não selecionar um grupo.
- O `/show` ganhou paginação e busca simples para grupos e moderadores.
- Limites no `/show` ganharam opção “outro valor”.
- DDX no `/show` passou a mostrar sugestão quando houver reincidência nas ocorrências recentes.
- Música no `/show` passou a ter botões para bloquear artista/faixa, adicionar catálogo, agendar grupo, pausar/retomar/remover agendamento e remover itens.
- O agendamento criado pelo `/show` nasce pausado para evitar disparo sem revisão.

## Limites conhecidos

- Upload real de foto do celular para mensagem do moderador ainda não foi implementado; continua URL HTTPS ou file_id.
- A sugestão de ban do DDX ainda não executa ban automaticamente, por decisão de segurança.
- O `/show` ainda usa entradas por texto quando precisa de valores livres, mas o início do fluxo é por botão.
