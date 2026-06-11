# Fase 11 — Etapa 9 — Pacote personalizado e contador de limites

## Revisão da Etapa 8

A revisão da Etapa 8 confirmou que o saneamento principal ficou válido: `release_check` em modo não estrito retorna `EXIT 0`, o bug de `convites.revogar` foi corrigido, e módulos legados passaram a ficar mais restritos para governante.

Dois pontos ainda exigiam correção antes de expandir o escopo:

1. A função `_require_canal_for_any_palco` havia ficado com um `if` duplicado. Era sintaticamente válido, mas confuso e frágil para manutenção.
2. O pacote personalizado ainda não existia de verdade, embora o escopo já previsse pacote por governante definido pelo owner.

## Entrega da Etapa 9

Esta etapa implementa a base real do pacote `personalizado` e melhora a visualização dos limites no Web App.

### Pacote personalizado

O backend agora aceita `pacote="personalizado"` no endpoint owner-only:

`POST /equalizador/api/governantes/pacotes`

Nesse caso, o payload pode incluir `actions`, por exemplo:

```json
{
  "usr_ref": "usr_xxx",
  "grp_ref": "grp_xxx",
  "pacote": "personalizado",
  "actions": ["mensagens.enviar", "membros.silenciar"]
}
```

As ações são sanitizadas por allowlist. O pacote personalizado não pode liberar ações fora do escopo governante, como DDX, logs, kick, lote, entradas e rádio legado.

### Gate por actions_json

A Etapa 9 corrige a lógica para que o gate do backend use `actions_json` quando o pacote for personalizado. Assim, o owner consegue liberar um subconjunto de ações para um governante em um grupo específico.

### Contador visual no Web App

O cabeçalho do grupo agora mostra:

- pacote atual;
- quantidade de ações liberadas;
- limites configurados;
- uso/restante diário;
- exceções ativas.

### Saneamento adicional

A função `_require_canal_for_any_palco` foi limpa para remover o `if` duplicado herdado do saneamento anterior.

O `openView` também passou a bloquear diretamente janelas owner-only para governante, mesmo se alguma navegação tentar abrir a view por estado salvo ou busca.

## Fora desta etapa

Ainda não foi implementado:

- formulário completo no `/show` para editar pacote personalizado por botões;
- transmissão musical automática por horários;
- tela owner para bloquear/desbloquear artista/faixa;
- resumo diário consolidado de limites.
