# Fase 11 — Etapa 17 — Alinhamento final UI/backend antes do deploy

## Objetivo

Esta etapa fecha desalinhamentos encontrados na auditoria ampliada pós-Etapa 16 entre pacote governante, interface, resolvers e endpoints.

A correção adotada foi conservadora: ações que dependem de listagens owner-only ou referências que o governante não deve acessar voltam a ficar fora dos pacotes governante até existir uma UI governante específica e segura para elas.

## Ajustes aplicados

1. O pacote Avançado/Personalizado deixou de oferecer, por enquanto:
   - `convites.editar`;
   - `convites.revogar`;
   - `reacoes.mensagem.limpar`;
   - `reacoes.recentes.limpar`;
   - `reacoes.reactor.silenciar`;
   - `canais_remetentes.banir`;
   - `canais_remetentes.liberar`.

2. O editor owner de pacote personalizado no Web App passou a listar apenas ações governante-operacionais com caminho visual seguro:
   - postar texto;
   - postar foto com legenda;
   - apagar mensagem;
   - fixar/desfixar;
   - silenciar/liberar;
   - banir/reintegrar;
   - criar convite com solicitação;
   - broadcast musical do governante.

3. Ações de reações, canais remetentes e edição/revogação de convite permanecem no backend para owner/maestro e módulos legados, mas não são mais vendidas como capacidade governante.

4. O resolver de mensagem continua restrito às ações que realmente usam `msg_ref` no escopo governante atual:
   - apagar mensagem;
   - fixar;
   - desfixar.

5. Foi removido retorno duplicado em `equalizador_palco_alvos`.

6. O texto interno `Restringir/remover membros` foi ajustado para `Restringir/banir membros`, evitando conflito com a regra de escopo: sem kick, ban unitário quando necessário.

## Decisão técnica

A decisão desta etapa é não abrir uma UI parcial para reações/canais remetentes/convites antigos. Essas ações exigem listagens ou referências sensíveis (`reaction_ref`, `sender_ref`, `invite_ref`) que a auditoria já classificou como owner-only no estado atual.

Quando houver demanda futura, essas ações devem entrar em fase própria com:

- tela governante restrita;
- listagem mínima por escopo;
- backend gate por pacote;
- testes de referência;
- logs e confirmação.

## Validação esperada

- Python compila.
- HTML/JS/IDs passam no guard.
- `node --check` passa nos scripts extraídos.
- `release_check` sai com `EXIT 0` em ambiente local sem modo estrito.
- Testes específicos da Fase 11 passam.
