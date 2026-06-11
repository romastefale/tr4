# FASE 11 — ETAPA 14 — PACOTE FINAL ACUMULADO E VALIDAÇÃO REAL

## Natureza da etapa

Esta etapa não adiciona recurso novo. Ela consolida o acumulado da Fase 11 até a Etapa 13 em um pacote final aplicável, com validação local e roteiro de validação real no Termux, Railway e Telegram.

## Escopo consolidado

O pacote final acumulado contém:

- endurecimento do painel Equalizador;
- validação HTML/JS/IDs embutidos;
- `/show` owner/maestro em DM;
- pacotes governante Básico, Moderador, Avançado e Personalizado;
- persistência de governante/grupo/pacote/ações;
- bloqueio backend de ação fora do pacote;
- limites diários por governante/grupo/ação;
- exceção de 24h por ação específica;
- aviso ao owner quando limite é atingido;
- DDX owner-only;
- fluxo DDX no `/show` para ativar, pausar, adicionar/remover palavra e ver ocorrências;
- postagem texto/foto com legenda e fixação quando permitido;
- apagar mensagem por link;
- ban/unban conforme escopo;
- convite único com solicitação;
- `/broadcast` owner em DM;
- broadcast musical governante pelo Web App;
- broadcast musical automático por horários;
- bloqueio global de artista/faixa;
- catálogo manual de músicas do owner;
- resumo diário consolidado de limites ao owner;
- saneamento de endpoints legados principais;
- release check em modo não estrito com saída 0 no ambiente local.

## Validação executada no pacote final

Comandos executados localmente:

```bash
python -m py_compile \
  app/bot/music_broadcast_core.py \
  app/bot/music_broadcast.py \
  app/bot/owner_daily_summary.py \
  app/bot/show_owner.py \
  app/main.py \
  app/equalizador/router.py \
  app/equalizador/governante_scope.py \
  app/equalizador/governante_webapp.py \
  scripts/validate_equalizador_embedded_html.py

python scripts/validate_equalizador_embedded_html.py --router app/equalizador/router.py

python -m pytest -q \
  tests/test_phase11a_embedded_html_js_guard.py \
  tests/test_phase11b_panel_hardening.py \
  tests/test_phase11_etapa2_show_owner.py \
  tests/test_phase11_etapa3_webapp_governante.py \
  tests/test_phase11_etapa4_ddx_owner_only.py \
  tests/test_phase11_etapa5_music_broadcast.py \
  tests/test_phase11_etapa6_governante_scope.py \
  tests/test_phase11_etapa7_governante_limits.py \
  tests/test_phase11_etapa8_saneamento_acumulado.py \
  tests/test_phase11_etapa9_personalizado_scope_ui.py \
  tests/test_phase11_etapa10_show_owner_painel.py \
  tests/test_phase11_etapa11_broadcast_auto_summary.py \
  tests/test_phase11_etapa12_broadcast_quality.py \
  tests/test_phase11_etapa13_technical_closure.py \
  tests/test_music_only_build.py

python scripts/equalizador_release_check.py
```

Resultado local:

```text
py_compile OK
HTML/JS/IDs OK
node --check OK
pytest: 49 passed, 14 skipped
release_check: EXIT 0
```

Os avisos restantes do release check são de ambiente local sem token/base URL pública. Não foram classificados como erro de código.

## Validação real obrigatória após aplicação

Depois de aplicar e subir para o Railway, validar nesta ordem:

1. abrir `/show` na DM do owner;
2. confirmar que `/show` não funciona para usuário comum;
3. confirmar que `/show` em grupo orienta usar no privado;
4. abrir player público;
5. abrir Painel pelo botão correto;
6. testar link direto `/equalizador` sem sessão;
7. cadastrar governante Básico;
8. testar postagem texto/foto;
9. cadastrar governante Moderador;
10. testar apagar por link;
11. testar ban/unban controlado em grupo pequeno;
12. cadastrar pacote Personalizado;
13. testar ação permitida e ação bloqueada;
14. configurar limite diário pequeno;
15. atingir limite e confirmar bloqueio;
16. confirmar DM ao owner;
17. liberar exceção 24h;
18. testar DDX owner-only;
19. adicionar/remover palavra DDX via `/show`;
20. testar `/broadcast` owner com música atual Last.fm;
21. testar broadcast governante pelo Web App;
22. criar agendamento musical com prévia;
23. bloquear/desbloquear artista/faixa;
24. adicionar música ao catálogo manual;
25. aguardar execução automática;
26. verificar resumo diário de limites após 23:55 America/Sao_Paulo.

## Limites conhecidos

- Os testes locais têm skips por dependências opcionais ausentes neste ambiente.
- A validação real depende de Bot API, grupos reais, permissões reais do bot e variáveis de ambiente de produção.
- O agendamento automático é best-effort e depende do processo do bot estar ativo no horário configurado.
- O catálogo manual exige capa/card para envio automático; item sem mídia não deve ser enviado.

## Recomendação de aplicação

Aplicar em um repositório limpo, rodar validações, commitar e subir. Depois acompanhar logs do Railway antes de testar grupos principais.
