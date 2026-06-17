# Tigrão FSM isolado — Etapa 01

Este diretório prepara a estrutura isolada do plugin Tigrão FSM no TR4 sem conectá-lo ao `main.py`, ao webhook real ou ao dispatcher.

## Fonte importada do Tigrão original

Foram inspecionados `RELATORIO_TIGRAO_FSM_TR3.md`, `MANIFESTO_TIGRAO_FSM_TR3.json` e `tigrao_fsm_isolado_TR3_0e5929e.zip`. A fonte mais completa é o ZIP, que contém `fonte_original_tr3/app/moderation_tigrao/` com routers, FSM própria, storage, keyboards, DDX, DDX soft, X9 inline, reações, customização, mídia fixada e dependências de integração.

## Fora do escopo desta etapa

Não foram ativados DDX hard, DDX soft, X9, reactions, solicitações de entrada, autoaceite, watch de membro novo, painel de diagnóstico, `/tr4check`, `/tr4usage`, sidecar ou resposta pública em grupo.

## Ainda não conectado ao TR4

`main.py` e `app/bot/telegram.py` não foram alterados. Nenhum router é registrado no dispatcher e nenhum hook `before_dispatch` é conectado ao webhook real.

## Conexão futura

A conexão futura deverá ocorrer por ponto único de montagem, preferencialmente `build_tigrao_fsm_plugin()`, feature flags e hook isolado `tigrao_plugin.before_dispatch(bot, update)`, sem imports diretos espalhados no core.

## Submódulos

- `state.py`: FSM própria em memória, com timeout de 15 minutos.
- `keyboards.py`: namespace `tgf:` e botões `primary`, `success` e `danger`.
- `plugin.py` e `mount.py`: contêiner e montagem futura sem dispatcher ativo.
- `permissions.py`, `storage.py`, `texts.py`: stubs explícitos de autorização, storage e textos.
- `routers/`: stubs por área do painel.
- `runtime/`: stubs de hooks futuros.

## Riscos de acoplamento evitados

Foram evitados imports de `app.main`, alterações no fluxo musical, registro de routers no dispatcher e conexão direta de DDX ao webhook.

## Revisão nas etapas 2 e 3

Revisar autorização real, compatibilidade de botões coloridos com a versão de aiogram instalada, schema de storage, montagem por flags, logs por grupo selecionado e migração cuidadosa dos callbacks antigos `tigrao:` para o namespace `tgf:`.
