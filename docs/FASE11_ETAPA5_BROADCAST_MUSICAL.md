# Fase 11 — Etapa 5 — Broadcast musical e fechamento

## Objetivo

Fechar o bloco de cinco etapas com uma primeira implementação funcional e segura do broadcast musical:

- owner usa `/broadcast` apenas em DM;
- prévia obrigatória antes do envio;
- seleção por `all` ou por números dos grupos conhecidos;
- governante usa ação do Web App apenas no grupo atual;
- governante não escolhe destino, não fixa e não envia silencioso;
- bloqueio global por artista/faixa;
- registro de execução e resultado por grupo;
- envio best-effort de tcanvas: vídeo quando houver Canvas, capa quando houver card; sem card/canvas, não envia.

## Owner

Fluxo:

1. Owner envia `/broadcast` na DM.
2. Bot busca a música atual do owner no Last.fm/Spotify conectado.
3. Bot mostra prévia e lista numerada de grupos conhecidos.
4. Owner envia `/broadcast all`, `/broadcast 1,3` ou usa botões rápidos.
5. O bot envia e registra resultado.

O comando `/broadcast` foi adicionado somente ao escopo privado de comandos.

## Governante Web App

O painel recebeu a ação “Enviar música atual”. Ela chama:

`POST /equalizador/api/palcos/{grp_ref}/musica/broadcast-atual`

Regras:

- usa a música atual do governante;
- envia apenas no grupo atual do painel;
- exige canal `mensagens.enviar` no backend;
- não fixa;
- não envia silencioso;
- não permite escolher destino;
- registra log de resultado.

## Limitações conscientes

Esta etapa não implementa ainda:

- agendamento automático de tcanvas por horários;
- tela owner completa para bloquear/desbloquear artista/faixa;
- UI de seleção múltipla rica no Telegram além de `/broadcast 1,3`;
- limite diário persistente por governante;
- fixar broadcast owner por configuração padrão.

Esses itens ficaram preparados pelo serviço e pelos logs, mas não devem ser tratados como completos.

## Validação

- Python compile nos módulos alterados.
- Guard HTML/JS/IDs do Equalizador.
- Testes de contrato do broadcast musical.
