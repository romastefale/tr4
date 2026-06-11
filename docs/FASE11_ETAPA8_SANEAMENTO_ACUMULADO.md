# Fase 11 — Etapa 8 — Saneamento do acumulado

## Objetivo

Corrigir os pontos detectados na revisão geral até a Etapa 7 antes de expandir novos recursos.

## Correções aplicadas

1. Corrigido o fluxo de `convites.revogar`.
   - Antes, a revogação executava e depois caía no retorno de `exportar_link_primario`.
   - Agora `revogar` retorna o resultado da revogação e registra uso quando aplicável.

2. `convites.exportar_primario` passou a registrar uso quando acionado por governante não-maestro.

3. `entradas.aprovar` e `entradas.recusar` agora passam pelo gate governante.
   - Como essas ações não pertencem aos pacotes governante atuais, ficam restritas a owner/maestro salvo futura liberação explícita.

4. `novos-membros` agora passa pelo gate governante nas ações operacionais.
   - Ações de novos membros não pertencem ao escopo governante atual.
   - Governante não deve operar esse módulo por endpoint direto.

5. `reacoes.reactor.silenciar` agora passa pelo gate governante e pelo limite diário.

6. Módulo Rádio legado foi restringido a owner/maestro no backend.
   - O broadcast musical governante continua no endpoint próprio `/musica/broadcast-atual`.

7. Interface também passa a esconder/desabilitar módulos legados fora do escopo governante.
   - Rádio, reações, histórico, tópicos, perfil, novos membros e áreas técnicas ficam fora do governante comum.

8. Confirmação backend adicionada para ações sensíveis.
   - Chamadas diretas sem `confirmacao="CONFIRMAR AJUSTE"` retornam 428.
   - Frontend injeta essa confirmação após confirmação inline.

9. `reaction_audit` removido das listas críticas do runtime Equalizador.
   - O `release_check` não acusa mais resíduo antigo em `app/`.
   - Scripts históricos de importação TR3 permanecem fora do scan de app.

## Ações que agora exigem confirmação backend

- `mensagens.enviar`
- `mensagens.enviar_foto`
- `mensagens.apagar`
- `mensagens.apagar_lote`
- `membros.silenciar`
- `membros.remover`
- `convites.revogar`
- `entradas.recusar`
- `reacoes.mensagem.limpar`
- `reacoes.recentes.limpar`
- `reacoes.reactor.silenciar`
- `canais_remetentes.banir`
- `novos.apagar`
- `novos.silenciar`
- `novos.banir`

## O que não foi feito

- Não foi implementado pacote personalizado.
- Não foi implementado FSM completo no `/show` para configurar todos os itens por botão.
- Não foi implementada transmissão musical automática por horários.
- Não foram removidos scripts históricos de importação TR3.

## Validação esperada

- `py_compile` sem erro.
- Guard HTML/JS/IDs sem erro.
- `node --check` sem erro.
- Testes específicos passando.
- `equalizador_release_check.py` sem erro em modo não estrito.
