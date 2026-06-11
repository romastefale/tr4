# Fase 11 — Etapa 15 — Auditoria corretiva pós pacote final

## Objetivo

Corrigir os pontos identificados na auditoria final pós Etapa 14 antes de qualquer deploy real.

## Correções aplicadas

1. **GETs legados passam a ser owner-only no backend**
   - `/api/historico`
   - `/api/historico/exportar`
   - `/api/palcos/{grp_ref}/entradas`
   - `/api/palcos/{grp_ref}/convites`
   - `/api/palcos/{grp_ref}/topicos`
   - `/api/palcos/{grp_ref}/canais-remetentes`
   - `/api/palcos/{grp_ref}/novos-membros`
   - `/api/palcos/{grp_ref}/reacoes/auditoria`

2. **O frontend não chama mais leituras owner-only para governante**
   - `loadPalcoData()` agora só chama histórico, entradas, convites, tópicos, canais remetentes, rádio legado, reações auditoria e novos membros quando `modoMaestroPermitido` é verdadeiro.

3. **`convites.exportar_primario` corrigido**
   - deixou de exigir `convites.criar`;
   - passa a exigir `convites.ver`;
   - continua fora dos pacotes governante, portanto fica restrito a owner/maestro na prática.

4. **Pacote Avançado e Personalizado ampliados dentro do escopo governante**
   - Avançado agora inclui ações operacionais extras: silenciar/liberar, fixar/desfixar, editar/revogar convite, limpar reações e canais remetentes.
   - Personalizado usa o mesmo conjunto autorizável do Avançado.
   - Permanecem bloqueados: logs, histórico, DDX, entradas, tópicos, rádio legado, lote, kick e exportação de link primário.

5. **Rótulo “Remover membro” corrigido para “Banir membro”**
   - mantém o action code legado `membros.remover` por compatibilidade interna;
   - altera o texto de interface e mensagens públicas para refletir a decisão de escopo: ban, não kick.

## Validação

- `py_compile` OK.
- Validação HTML/JS/IDs OK.
- `node --check` OK.
- `release_check` EXIT 0, com avisos apenas de ambiente local.
- Testes específicos: `54 passed, 14 skipped`.

## Limite conhecido

A suíte completa ainda depende das dependências reais do projeto no ambiente Termux/Railway. Os `skipped` locais vêm de dependências opcionais não disponíveis neste container.
