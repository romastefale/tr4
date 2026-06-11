# Fase 11 — Etapa 7 — Limites diários reais e exceção 24h

## Revisão aplicada sobre a Etapa 6

A revisão encontrou um erro técnico real na Etapa 6: `assignment_ref` era derivado de `hash()` do Python. Esse hash é randomizado por processo, então poderia mudar entre reinícios e tornar referências persistentes instáveis. A Etapa 7 corrige isso usando `hashlib.sha256`, mantendo o mesmo prefixo público `gpk` sem expor IDs brutos.

A Etapa 6 também tinha tabelas de limite e registro de uso, mas ainda não bloqueava ações. Isso foi corrigido nesta etapa.

## Implementação da Etapa 7

### Limites diários

A ação governante agora passa por validação de limite antes da execução. O fluxo ficou:

1. validar identidade;
2. validar canal/permissão do palco;
3. validar pacote liberado pelo owner;
4. validar limite diário;
5. executar a ação;
6. registrar uso após sucesso.

Se o limite configurado for `0` ou inexistente, a ação é considerada sem limite diário.

A data diária usa `America/Sao_Paulo`, para bater com o contexto operacional do projeto.

### Exceção de 24h

Foi criada uma tabela persistente de exceções:

- `eq_governante_limit_exceptions`.

A exceção é por:

- governante;
- grupo;
- ação específica;
- pacote ativo;
- expiração de até 24h.

A exceção pode ser revogada antes de expirar.

### Endpoints owner-only criados

- `POST /equalizador/api/governantes/pacotes/{assignment_ref}/excecoes`
- `DELETE /equalizador/api/governantes/excecoes/{exception_ref}`

Esses endpoints exigem owner/maestro.

### Aviso ao owner

Quando o governante atinge limite:

- backend bloqueia com HTTP 429;
- registra evento `EQUALIZADOR_GOVERNANTE_LIMITE_ATINGIDO`;
- envia DM best-effort para todos os maestros configurados;
- payload público informa ação, limite, uso e restante.

### O que ainda não entrou

- Botões visuais completos no `/show` para liberar exceção.
- Tela de contador detalhado por ação no Web App.
- Resumo diário consolidado; a regra atual continua aviso toda vez que bater limite.

## Validação

Validações executadas no ambiente local:

- `python -m py_compile app/equalizador/router.py app/equalizador/governante_scope.py app/equalizador/governante_webapp.py scripts/validate_equalizador_embedded_html.py`
- `python scripts/validate_equalizador_embedded_html.py --router app/equalizador/router.py`
- `python -m pytest -q` com testes específicos das fases 11A até 11 etapa 7.

Resultado local: `24 passed, 8 skipped`.

Os skips são por dependências opcionais ausentes no ambiente local, como `sqlalchemy`/`aiogram`, já tratados pelos testes com `importorskip`.

`equalizador_release_check.py` ainda retorna erro por resíduos antigos `reaction_audit` e avisos de ambiente sem token/base URL. Isso já existia e não foi causado pela Etapa 7.
