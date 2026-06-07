# Fase 55.10 — Segurança avançada, auditoria e exportações

Esta fase adiciona uma janela própria de segurança no Equalizador, restrita ao dono do código.

## Recursos

- Modo de segurança: normal, alerta e restrito.
- Auditoria sanitizada em banco.
- Exportação JSONL.
- Exportação assinada com HMAC-SHA256.
- Exportação criptografada com Fernet + PBKDF2-SHA256.
- Limpeza de auditoria antiga.
- Limpeza de locks e rate-limit em memória.
- Diagnóstico das fontes auditáveis.

## Privacidade

A interface não exibe IDs reais do Telegram. Eventos usam referências internas (`usr_`, `grp_`, `msg_`, `sec_`).

## Canais novos

```text
seguranca.ver
seguranca.modo
seguranca.exportar
seguranca.limpar
seguranca.sessoes
```

Todos são críticos e permanecem restritos ao dono do código pelo comportamento padrão do Equalizador.

## Modo restrito

Quando o modo restrito está ativo, ações de governantes são bloqueadas pela camada de segurança. Leituras operacionais continuam disponíveis onde aplicável; o dono do código pode atuar para retomar normalidade ou executar correções.

## Exportação criptografada

A senha precisa ter pelo menos 8 caracteres. A exportação retorna `salt_b64`, `conteudo_b64` e `sha256_plaintext` para conferência.
