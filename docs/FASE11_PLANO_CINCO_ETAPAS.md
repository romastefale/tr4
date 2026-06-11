# Fase 11 — Plano em cinco grandes etapas

## Etapa 1 — Base de segurança e integridade do painel

Objetivo: impedir regressões antes de aumentar poder do painel.

Escopo aplicado nesta entrega:

- Guard estático para HTML/JS embutido do Equalizador.
- Validação de IDs usados pelo JavaScript.
- `node --check` dos scripts extraídos.
- Shell negado para `GET /equalizador` sem sessão/cookie/autorização.
- Cookie curto `tr4_equalizador_eqs` criado pelo player antes de navegar ao painel.
- Revalidação server-side do cookie pela rota do painel.
- Confirmação inline para ações destrutivas comuns sem transformar essas ações em owner-only.

## Etapa 2 — FSM owner `/show`

Escopo futuro:

- `/show` só na DM do owner.
- Lista de grupos conhecidos.
- Diagnóstico de capacidade por grupo.
- Permissões reais do bot.
- O que falta para capacidade total.
- Liberação manual de governantes, grupos, pacotes e ações.

## Etapa 3 — Web App governante e ações imediatas

Escopo futuro:

- Pacotes Básico, Moderador, Avançado e Personalizado.
- Postar texto.
- Postar foto com legenda.
- Postar e fixar.
- Apagar mensagem por link.
- Ban/unban por ID validado ou link de mensagem.
- Convite único com solicitação.
- Limites diários por ação, governante e grupo.

## Etapa 4 — DDX owner-only

Escopo futuro:

- Configuração só pelo owner.
- Palavras/frases simples.
- Normalização básica.
- Apagamento silencioso.
- Log completo para owner.
- Pausa por grupo.
- Reincidência global por usuário.
- Sugestão de ban após 5 apagamentos.

## Etapa 5 — Broadcast musical e fechamento

Escopo futuro:

- `/broadcast` owner.
- Broadcast musical no Web App governante.
- Transmissão musical automática por grupo.
- Tcanvas com nome exato do grupo como ouvinte.
- Bloqueio global de artista/música.
- Logs, limites e validação final.
