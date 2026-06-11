# Fase 11 — Etapa 6 — Integração real do escopo governante

## Objetivo

Transformar o contrato das cinco etapas anteriores em uma primeira camada real de backend: o owner passa a ter uma estrutura persistente para liberar pacote de Web App por governante e por grupo, e o backend passa a bloquear ações fora do pacote liberado.

## O que mudou

- Criado `app/equalizador/governante_scope.py`.
- Criadas tabelas persistentes:
  - `eq_governante_assignments`;
  - `eq_governante_daily_limits`;
  - `eq_governante_daily_usage`.
- Criados endpoints owner-only:
  - `GET /equalizador/api/governantes/pacotes`;
  - `POST /equalizador/api/governantes/pacotes`;
  - `DELETE /equalizador/api/governantes/pacotes/{assignment_ref}`;
  - `POST /equalizador/api/governantes/pacotes/{assignment_ref}/limites`.
- `/equalizador/api/me` agora inclui `governante_scope` para o frontend saber quais ações pertencem ao pacote do governante no grupo.
- `_execute_action_endpoint`, `_execute_avancado_endpoint`, convite extra e broadcast musical do governante passam por `_require_governante_scope_for_action`.
- Ações fora de pacote retornam 403 com erro público seguro.
- Uso diário é registrado em `eq_governante_daily_usage` para ações governante executadas com sucesso.
- UI do Web App passa a desabilitar ações fora do pacote e esconder módulos fora do escopo governante.

## Escopo atendido

- Integrar pacote governante ao backend: atendido.
- Persistir governante/grupo/pacote: atendido em `eq_governante_assignments`.
- Bloquear ação fora do pacote: atendido no backend para ações operacionais principais.
- Esconder/desabilitar módulos fora do escopo: atendido no frontend como UX preventiva.
- Preparar base de limites diários: atendido com tabelas e endpoints de configuração.
- Criar testes funcionais de autorização por pacote, grupo e ação: parcialmente atendido com testes estáticos/contratuais; testes runtime com SQLAlchemy devem rodar no ambiente completo.

## Limites honestos desta etapa

- Ainda não há conversa FSM completa no `/show` para cadastrar pacote por botões.
- Ainda não há tela refinada de pacotes no painel; os endpoints já existem para integração.
- A base de limites diários está criada e o uso é registrado, mas bloqueio por limite e exceção de 24h ficam para a próxima etapa.
- Os testes locais são limitados porque o ambiente atual não tem SQLAlchemy instalado.

## Validação esperada

```bash
python -m py_compile app/equalizador/router.py app/equalizador/governante_scope.py app/equalizador/governante_webapp.py scripts/validate_equalizador_embedded_html.py
python scripts/validate_equalizador_embedded_html.py --router app/equalizador/router.py
python -m pytest -q tests/test_phase11_etapa6_governante_scope.py
```
