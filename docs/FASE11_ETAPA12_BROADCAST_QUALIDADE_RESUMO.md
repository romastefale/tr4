# Fase 11 — Etapa 12 — Correção de qualidade do broadcast automático e resumo

## Objetivo

Corrigir os pontos encontrados na revisão da Etapa 11 antes de tratar o broadcast musical como fechado.

## Correções aplicadas

1. `track_identity()` agora reconhece os campos usados pelo TR4/Last.fm/Spotify:
   - `album_image_url`;
   - `spotify_url`;
   - `cover_url`;
   - `image_url`;
   - `spotify_id`.

2. `/broadcast` owner manual passou a aceitar somente música atualmente tocando no Last.fm.
   - Não usa música antiga.
   - Não usa fallback Spotify.
   - Se Last.fm não indicar `nowplaying=true`, não envia.

3. Broadcast musical governante no Web App passou a aceitar somente música atualmente tocando no Last.fm.
   - Não usa última música.
   - Não usa fallback Spotify.

4. Agendamento automático passou a exigir prévia inicial real:
   - Web App chama endpoint de prévia antes de criar;
   - backend retorna `428` se tentar criar sem `preview_confirmed=true`;
   - comando `/broadcast schedule` exige repetição com `confirmar`.

5. Scheduler automático não dispara mais slots antigos atrasados.
   - Antes: qualquer slot anterior ao minuto atual podia disparar após restart/processamento manual.
   - Agora: só dispara no minuto local exato configurado.

6. Falhas do scheduler sem música disponível agora são registradas nas tabelas de broadcast.

7. Resumo diário consolidado de limites agora é enviado por DM ao owner, uma vez por dia, após 23:55 no fuso `America/Sao_Paulo`.
   - Usa tabela `eq_governante_daily_summary_dispatch` para evitar duplicidade após restart.

## Validação

- `py_compile` OK.
- Validação HTML/JS/IDs OK.
- `node --check` OK.
- `pytest` específico OK.
- `equalizador_release_check.py` EXIT 0, com avisos apenas de ambiente local sem token/base URL pública.

## Limites conhecidos

- A seleção automática ainda é best-effort e amostra perfis conhecidos.
- A lista manual de músicas do owner ainda não foi modelada como catálogo próprio.
- A entrega de resumo por DM depende de o owner já ter aberto conversa privada com o bot.
