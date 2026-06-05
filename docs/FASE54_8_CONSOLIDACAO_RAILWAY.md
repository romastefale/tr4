# Fase 54.8 — Consolidação final Railway

Esta etapa fecha o ciclo Fase 54 para aplicação em GitHub/Railway. Ela não adiciona nova ação de Telegram; consolida documentação, variáveis, roteiro de aplicação, critérios de teste e pontos de atenção para logs.

## Escopo consolidado

Fases incluídas no pacote final:

- 54.1 — Equalizador em janelas internas, com navegação por áreas e maior contraste.
- 54.2 — Perfil do grupo com foto, troca de foto e remoção de foto.
- 54.3 — Mensagens, envio, fixação, desfixação, apagar e resolver link.
- 54.4 — Pessoas, administradores humanos, bots administradores, membros vistos e referências internas seguras.
- 54.5 — Convites e tópicos em janelas separadas.
- 54.6 — Diagnóstico real de permissões, cruzando canal do operador, direito real do bot e restrição de Maestro.
- 54.7 — Normalização sanitizada de erros Telegram 400/403/409/429/5xx.
- 54.8 — Consolidação para aplicação, revisão de variáveis e roteiro de teste Railway.

## Banco persistente

O ponto crítico é preservar o banco SQLite que já contém tokens e dados musicais. O caminho recomendado para Railway é:

```text
TR3_DATABASE_URL=sqlite:////app/data/app.db
```

Se o banco antigo do TR3 tiver outro nome, use exatamente o arquivo antigo. Não crie um arquivo novo apenas porque o pacote sugere outro nome. Se o app subir com banco vazio, Spotify poderá pedir `/login` novamente.

O volume Railway deve estar montado em:

```text
/app/data
```

## Variáveis mínimas do Equalizador

Para manter desligado ou fazer rollback lógico:

```text
TR4_EQUALIZADOR_ENABLED=false
TR4_EQUALIZADOR_APP_NAME=equalizador
TR4_EQUALIZADOR_HIDE_TECHNICAL_IDS=true
TR4_EQUALIZADOR_INITDATA_MAX_AGE_SECONDS=600
TR4_EQUALIZADOR_SESSION_TTL_SECONDS=900
TR4_EQUALIZADOR_RATE_LIMIT_PER_MINUTE=30
```

Para ligar para Maestro com todos os canais:

```text
TR4_EQUALIZADOR_ENABLED=true
TR4_EQUALIZADOR_APP_NAME=equalizador
TR4_EQUALIZADOR_MAESTRO_IDS=8505890439
TR4_EQUALIZADOR_OPERADOR_IDS=8505890439
TR4_EQUALIZADOR_PALCO_IDS=-1000000000000
TR4_EQUALIZADOR_CANAIS=8505890439:*:*
TR4_EQUALIZADOR_HIDE_TECHNICAL_IDS=true
TR4_EQUALIZADOR_INITDATA_MAX_AGE_SECONDS=600
TR4_EQUALIZADOR_SESSION_TTL_SECONDS=900
TR4_EQUALIZADOR_RATE_LIMIT_PER_MINUTE=30
```

Canais adicionados no ciclo 54, caso não use `*`:

```text
mensagens.enviar
grupo.foto
grupo.foto.remover
```

## Comando Termux/GitHub

Após baixar o ZIP para Downloads, o formato de aplicação esperado é:

```bash
cd ~/tr4 && git checkout main && git pull origin main && ZIP="/storage/emulated/0/Download/TR4-clean-phase54-8-consolidacao-railway.zip" && test -f "$ZIP" && rm -rf ~/tr4_apply_tmp && mkdir -p ~/tr4_apply_tmp && unzip -q "$ZIP" -d ~/tr4_apply_tmp && SRC="$(find ~/tr4_apply_tmp -type d -name app -print -quit | sed 's#/app$##')" && test -n "$SRC" && rsync -a --delete --exclude=".git" "$SRC/" ~/tr4/ && python -m compileall app scripts tests && git add -A && git commit -m "Fase 54.8: consolida Equalizador para Railway" || true && git push origin main
```

Se o comando não imprimir nada, não recole o comando grande. Teste primeiro:

```bash
echo OK
```

Se `echo OK` não responder, a sessão do Termux está travada ou aguardando fechamento de aspas/comando.

## Validação local

```bash
python -m compileall -q app scripts tests
PYTHONPATH=. pytest -q
PYTHONPATH=. python scripts/equalizador_release_check.py
```

Validação estrita em ambiente com variáveis configuradas:

```bash
PYTHONPATH=. python scripts/equalizador_release_check.py --strict
PYTHONPATH=. python scripts/smoke_imports.py
```

## Teste final no Railway

1. Confirmar deploy sem resetar volume.
2. Abrir `/healthz`.
3. Abrir `/readyz`.
4. Abrir o Mini App pelo link interno do Telegram.
5. Selecionar grupo.
6. Conferir janela Diagnóstico.
7. Testar Perfil do grupo: título, descrição, foto.
8. Testar Mensagens: enviar, enviar e fixar, desfixar, apagar.
9. Testar Pessoas: administradores humanos, bots administradores e título personalizado.
10. Testar Convites e Tópicos.
11. Ler logs Railway e procurar códigos 400/403/409/429 normalizados.

## Critério de aceitação

A Fase 54.8 está aceita quando:

- o app sobe no Railway;
- o banco antigo permanece disponível;
- o Spotify não pede `/login` por banco novo;
- o Equalizador mostra nomes públicos e `@username` quando houver;
- IDs reais não aparecem na interface;
- foto de grupo é tentada e erros aparecem normalizados;
- botões ficam separados por janela funcional;
- Diagnóstico mostra o motivo antes da ação;
- Histórico não vaza payload técnico ou IDs reais.
