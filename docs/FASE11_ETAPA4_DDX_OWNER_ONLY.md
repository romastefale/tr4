# Fase 11 — Etapa 4 — DDX owner-only

## Objetivo

Esta etapa alinha o DDX ao escopo fechado: DDX não é função do governante no Web App. A configuração fica restrita ao owner/maestro, o apagamento é silencioso, os logs ficam internos ao owner e a automação não executa ban sozinha.

## Decisões aplicadas

- DDX passa a ser tratado como área owner-only.
- Governante não vê, não configura e não recebe logs do DDX.
- Endpoints `/equalizador/api/palcos/{grp_ref}/ddx` exigem maestro, além da identidade e permissões já existentes.
- DDX 10 minutos foi desativado para novas configurações no escopo atual.
- O modo operacional do escopo passa a ser único: apagamento silencioso imediato por palavra/frase proibida.
- Mensagem de canal remetente não é apagada automaticamente: gera alerta para owner.
- Mensagem encaminhada só entra no fluxo se contiver palavra/frase proibida.
- O evento passa a guardar `actor_user_id`, `actor_kind` e `full_text` quando disponível.
- Após reincidência global igual ou superior a 5 apagamentos do mesmo usuário, o owner recebe sugestão de ban, sem execução automática.

## O que não foi feito nesta etapa

- Não foi criado ban automático.
- Não foi criado painel governante de DDX.
- Não foi removido o DDX legado do banco, para evitar perda de dados.
- Não foi implementada interface completa de configuração por FSM conversacional; o `/show` foi apenas atualizado para declarar a regra owner-only.

## Validação esperada

- `python -m py_compile app/equalizador/router.py app/equalizador/ddx.py app/bot/show_owner.py`
- `python scripts/validate_equalizador_embedded_html.py --router app/equalizador/router.py`
- `python -m pytest -q tests/test_phase11_etapa4_ddx_owner_only.py`
