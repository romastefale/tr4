# Fase 131 — diagnóstico funcional público

Esta fase evita falsos positivos de HTTP 200 no player público.

Adicionado:

- `/equalizador/api/public/diagnostico` para validar sessão, menu fixo, preview musical e grupos cacheados.
- `/equalizador/api/public/home` permanece rápido e não executa `getChatMember` em lote.
- `/equalizador/api/public/playing-preview` usa o mesmo payload base do fluxo musical existente.

A validação real de presença em grupo continua no momento de publicar `/nowp`.
