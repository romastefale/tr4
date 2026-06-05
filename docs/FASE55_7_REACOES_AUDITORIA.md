# Fase 55.7 — Reações, auditoria e reactors

## Escopo

Esta fase reimplanta no Equalizador o bloco de reações que existia no TR3, sem expor ID real na interface.

Foram adicionados:

- auditoria de updates `message_reaction` recebidos pelo webhook;
- registro de eventos recentes de reação;
- lista de reactors recentes por grupo;
- seleção de reactor por referência interna;
- limpeza de reações recentes usando o fluxo já existente;
- silêncio de reactor em modo conservador, preservando mensagens comuns quando possível;
- nova janela **Reações** no Mini App.

## Canais novos

```text
reacoes.auditoria
reacoes.reactor.silenciar
```

Canais já existentes usados pela janela:

```text
reacoes.limpar
reacoes.recentes.limpar
```

## Webhook

O webhook passa a solicitar explicitamente updates:

```text
message_reaction
message_reaction_count
```

A auditoria grava somente dados sanitizados para a interface. IDs reais de usuário, grupo e mensagem permanecem server-side.

## Banco

Tabelas novas:

```text
eq_reaction_events
eq_reaction_recent
```

## Limitação técnica honesta

O Bot API não oferece, em todas as versões/ambientes, uma permissão individual chamada literalmente “pode reagir”. Por isso o botão **Silenciar reactor** usa a restrição individual mais estreita disponível de forma geral: preserva envio comum de mensagens/mídias e desativa `can_send_other_messages` durante a duração escolhida. Quando o Telegram não permitir esse recorte, a falha retorna normalizada no painel.
