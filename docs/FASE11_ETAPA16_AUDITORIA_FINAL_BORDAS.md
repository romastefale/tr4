# FASE 11 — ETAPA 16 — AUDITORIA FINAL DE BORDAS

## Objetivo

Fechar as bordas restantes apontadas na auditoria pós-Etapa 15, sem criar recurso novo.

## Correções aplicadas

1. **Multimídia nativa virou owner-only no backend.**
   - Endpoints `/multimidia/centro`, `/multimidia/sessoes`, `/diagnostico` e `/publicar` agora chamam `_require_owner_only_module(identity, module="multimidia")`.
   - O Web App também não recarrega sessões multimídia para governante.

2. **Resolvers manuais passam pelo gate de pacote governante.**
   - Resolver mensagem exige que governante tenha pelo menos uma ação relacionada: `mensagens.apagar`, `fixados.criar` ou `fixados.remover`.
   - Resolver alvo exige pelo menos uma ação relacionada: `membros.silenciar`, `membros.liberar`, `membros.remover` ou `membros.reintegrar`.

3. **Mapa JS de convite corrigido.**
   - `convites.exportar_primario` agora aponta para `convites.ver`, alinhado ao backend.

4. **DDX 10 minutos foi marcado como legado.**
   - Labels públicas de canais/diagnóstico foram ajustadas para `DDX 10 minutos (legado)`.
   - O item foi removido do grupo principal de diagnóstico de ações do painel.

5. **Rótulos “Remover membro” foram substituídos por “Banir membro”.**
   - O código de ação interno `membros.remover` foi preservado por compatibilidade.

6. **Refs que usavam `hash()` foram estabilizadas.**
   - `rbac_runtime.py` e `seguranca_avancada.py` agora usam `hashlib.sha256`.

7. **Estado final consolidado.**
   - Criado `docs/FASE11_ESTADO_FINAL.md` para evitar confusão entre docs históricas e o estado final.

## Validação esperada

- `py_compile` OK.
- Validação HTML/JS/IDs OK.
- `node --check` OK.
- `release_check` EXIT 0.
- Testes específicos da Fase 11 OK.
