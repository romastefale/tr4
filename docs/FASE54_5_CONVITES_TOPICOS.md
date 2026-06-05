# Fase 54.5 — Convites e tópicos

Esta etapa reorganiza as janelas de Convites e Tópicos do Equalizador sem alterar regras de autenticação ou canais existentes.

## Convites

- Separa criação, resultado e convite selecionado.
- Exibe resumo de convites ativos, revogados e conhecidos.
- Permite copiar/abrir o link exibido ou o convite selecionado.
- Bloqueia edição/revogação de convite já revogado na interface.
- Mantém o link como dado operacional do convite; IDs técnicos continuam ausentes da UI.

## Tópicos

- Separa criação/renomeação, tópico selecionado e tópico geral.
- Exibe resumo de tópicos abertos, fechados, apagados e conhecidos.
- Bloqueia operação sobre tópico marcado como apagado.
- Mantém referências internas no seletor sem expor IDs numéricos do Telegram.

## Escopo

Não adiciona novos métodos Telegram e não altera permissões. O objetivo é clareza operacional antes da etapa de diagnóstico real de permissões.
