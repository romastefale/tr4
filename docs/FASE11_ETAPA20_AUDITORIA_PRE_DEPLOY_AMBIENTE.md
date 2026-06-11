# Fase 11 — Etapa 20 — Auditoria pré-deploy de ambiente, banco e startup

## Objetivo

Esta etapa não adiciona recurso funcional. Ela revisa o pacote acumulado da Fase 11 sob a ótica de produção: dependências, variáveis de ambiente, criação de tabelas, imports de startup, schedulers e comando final de aplicação.

## Resultado da auditoria local

Validações executadas no pacote acumulado:

- `py_compile`: OK.
- `compileall`: OK.
- HTML/JS/IDs: OK.
- `node --check`: OK.
- `equalizador_release_check.py`: EXIT 0, com avisos apenas por ausência de token/base URL pública no ambiente local.
- `phase11_final_check.sh`: OK.
- Testes específicos da Fase 11: 74 passed, 14 skipped no container usado para geração.

A suíte completa não pôde ser validada neste container porque faltam dependências como `SQLAlchemy` e `aiogram`. O projeto declara essas dependências em `requirements.txt`, então a validação obrigatória final deve ser feita no Termux/Railway com o ambiente completo.

## Correção aplicada nesta etapa

O startup respeita agora `RADIO_SCHEDULER_ENABLED` ao iniciar o scheduler legado de rádio. Antes, a variável existia em `settings.py`, mas o loop de rádio era iniciado sempre que `TR4_EQUALIZADOR_ENABLED` e token estivessem presentes.

Isso reduz risco operacional de iniciar scheduler legado por engano enquanto a Fase 11 testa broadcast musical e painel.

## Pontos verificados

### Dependências

O `requirements.txt` declara:

- `aiogram==3.27.0`
- `fastapi==0.116.1`
- `httpx==0.28.1`
- `SQLAlchemy==2.0.41`
- `uvicorn==0.35.0`
- `Pillow==11.3.0`
- `playwright==1.56.0`
- `pytest`
- `pytest-asyncio`
- `cryptography==46.0.4`

Antes do deploy, rode:

```bash
python -m pip install -r requirements.txt
python -m pip check
```

### Banco

A Fase 11 adiciona/cria em tempo de uso tabelas de governante, limites, exceções, broadcast, catálogo, resumo diário e DDX. O novo script `scripts/phase11_predeploy_env_check.sh` cria um SQLite temporário e valida a criação das tabelas principais.

Tabelas esperadas na validação temporária:

- `eq_governante_assignments`
- `eq_governante_daily_limits`
- `eq_governante_daily_usage`
- `eq_governante_limit_exceptions`
- `eq_governante_daily_summary_dispatch`
- `eq_music_broadcast_blocks`
- `eq_music_broadcast_runs`
- `eq_music_broadcast_results`
- `eq_music_broadcast_schedules`
- `eq_music_broadcast_catalog`
- `eq_ddx_filters`
- `eq_ddx_events`
- `eq_ddx_soft_pending`

### Startup

O app importa os routers e jobs principais sem iniciar rede no import. Os loops de background só rodam no startup e são condicionados por token e flags.

Pontos de startup:

- `app.bootstrap` chama `uvicorn.run("app.main:app")`.
- `app.main` executa `init_db()`, `run_migrations(engine)` e guards de persistência no startup.
- `MUSIC_BROADCAST_SCHEDULER` e `DDX` só iniciam com token e Equalizador habilitado.
- `RADIO_SCHEDULER` agora respeita `RADIO_SCHEDULER_ENABLED`.

### Variáveis críticas

Obrigatórias para operação real:

- `TR3_TELEGRAM_BOT_TOKEN` ou `TELEGRAM_BOT_TOKEN`
- `TR3_BASE_URL` ou `BASE_URL`
- `TR3_SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_ID`
- `TR3_SPOTIFY_CLIENT_SECRET` / `SPOTIFY_CLIENT_SECRET`
- `TR3_LASTFM_API_KEY` / `LASTFM_API_KEY`

Para Equalizador/Fase 11:

- `TR4_EQUALIZADOR_ENABLED=1`
- `TR4_EQUALIZADOR_MAESTRO_IDS`
- `TR4_EQUALIZADOR_OPERADOR_IDS`
- `TR4_EQUALIZADOR_PALCO_IDS`
- `TR4_EQUALIZADOR_CANAIS`, se usado para canais finos

Banco/volume:

- preferir `/data/app.db` via volume Railway;
- se usar `TR3_DATABASE_URL`, precisa ser SQLite;
- `DATABASE_URL` legado Postgres é ignorado se não for SQLite.

## Risco operacional restante

O maior risco restante não é código estático: é aplicar arquivo incremental errado.

Como várias etapas foram geradas sem deploy intermediário, a aplicação segura final deve usar o repositório completo da etapa final ou aplicar o pacote final acumulado sobre um checkout limpo. Não aplique só um `files.zip` incremental sobre uma base antiga.

## Validação obrigatória antes do push

No Termux/Railway/local com dependências completas:

```bash
python -m pip install -r requirements.txt
./scripts/phase11_predeploy_env_check.sh
python -m pytest -q
```

Se a suíte completa falhar, não subir para Railway antes de ler o erro.
