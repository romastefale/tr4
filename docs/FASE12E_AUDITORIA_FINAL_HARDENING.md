# Fase 12E — Auditoria final e hardening de inscrição X9

## Decisão

A Fase 12D manteve corretamente o X9 automático/DDX e separou o X9 contextual do FSM privado. A auditoria final encontrou um risco residual: um administrador Telegram de grupo desconhecido poderia acionar `/tmod` no grupo e, por consequência, fazer o X9 contextual cadastrar esse grupo como habilitado para o FSM privado.

Isso não expunha botões no grupo, mas era permissivo demais para produção.

## Correção

O trigger silencioso no grupo continua apagando a própria mensagem quando possível, porém só cadastra contexto de grupo desconhecido e só envia aviso em DM quando o usuário já é operador/dono configurado no TR4.

Administradores comuns do Telegram não criam escopo de FSM privado por trigger.

## Regra final

- X9 automático/DDX continua agindo como antes.
- X9 contextual alimenta o FSM privado apenas para grupos permitidos ou operadores configurados.
- Grupo não mostra menu, botão, erro ou confirmação operacional.
- Web App permanece player musical.
- Ações manuais permanecem em DM.

## Validação esperada

- `py_compile` OK.
- HTML/JS guard OK.
- `phase11_final_check.sh` OK.
- Testes FSM/X9 OK, incluindo guarda contra inscrição indevida de grupo desconhecido.
