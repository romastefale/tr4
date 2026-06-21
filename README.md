# TR4 Music Only

Bot Telegram com foco apenas musical.

## Start command

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Railway SQLite

Use volume em `/app/data` e variável:

```text
TR3_DATABASE_URL=sqlite:////app/data/tr4_music.sqlite3
```

## Validação

```bash
python -m compileall app scripts tests
PYTHONPATH=. python scripts/smoke_imports.py
PYTHONPATH=. pytest -q
```


<!-- TR4_DATABASE_RAILWAY_NOTE -->
## Railway / SQLite

TR4 music-only is SQLite-only. For Railway, use a persistent volume mounted at `/app/data`.
Set `TR3_DATABASE_URL=sqlite:////app/data/app.db` when possible. If an older Postgres `DATABASE_URL` remains from a previous service, TR4 ignores it unless it is already a SQLite URL.


## Escopo limpo

Esta base contém somente recursos musicais do TR4.
A escolha de grupo existe apenas para publicar resultado musical onde o usuário e o bot estão presentes.


## Songcharts universal

Todos os usuários importados em `lastfm_profiles` entram automaticamente no ranking universal. O mosaico `/tnow` usa a união de `spotify_tokens` e `lastfm_profiles`.

## Controles owner-only adicionados

- `/onoff` alterna o modo silencioso. Use `/onoff on`, `/onoff off` ou `/onoff status`. Quando ativo, usuários comuns só recebem `/start` e `/help`; mensagens, callbacks, inline queries e Web App autenticado ficam bloqueados. O owner definido em `TR4_CODE_OWNER_IDS` não é afetado.
- `/legacy` controla a restrição de logins antigos. Use `/legacy on`, `/legacy off`, `/legacy refresh` ou `/legacy release user_id`. O corte é `2026-06-15 00:00:00 UTC`. Usuários bloqueados podem sair da restrição reconectando com `/lastfm username` ou `/login`.
- `/listening` envia na DM do owner um `.txt` com os valores completos das tabelas de login e um `.pdf` textual organizado com os mesmos dados.

Observação técnica: `lastfm_profiles` já tinha `created_at/updated_at`. Em `spotify_tokens`, esta etapa adiciona `created_at/updated_at`; para linhas antigas sem esses campos, o boot aproxima o instante original por `expiration - 1 hora`, porque o banco anterior não guardava a data real de criação do login Spotify.

## Importação CSV Last.fm owner-only

Comando disponível somente na DM do owner:

```text
/lfmimportcsv
/lfmimportcsv confirm
/lfmimportcsv confirm limit=500
```

Envie um `.csv` anexado com legenda `/lfmimportcsv` para prévia. Para aplicar, use `confirm`. O bot envia por etapas, respeitando `TR3_LASTFM_SCROBBLE_IMPORT_BATCH_SIZE` (máximo técnico: 50 por chamada da API), pausa entre chamadas e pausa entre etapas. Se houver falhas, limite diário, HTTP 429 ou erro 29/rate limit do Last.fm, o bot para a execução, relata a etapa e gera CSV de retry/continuação.

Formato aceito:

```csv
artist,track,album,inject_count
Muse,The 2nd Law: Isolated System,,319
Home,Resonance,,313
```

Também aceita `artista,musica,reproducoes` e CSV expandido com uma linha por scrobble.

Variáveis relevantes no Railway:

```text
TR3_LASTFM_API_KEY=              # pode ser a mesma chave já usada para leitura Last.fm
TR3_LASTFM_API_SECRET=           # obrigatório para assinar track.scrobble
TR3_LASTFM_SESSION_KEY=          # sessão da conta Last.fm que receberá os scrobbles
TR3_LASTFM_SCROBBLE_IMPORT_MAX_PER_JOB=2000
TR3_LASTFM_SCROBBLE_IMPORT_STAGE_SIZE=250
TR3_LASTFM_SCROBBLE_IMPORT_BATCH_SIZE=50
TR3_LASTFM_SCROBBLE_IMPORT_SLEEP_SECONDS=1.2
TR3_LASTFM_SCROBBLE_IMPORT_STAGE_SLEEP_SECONDS=10
TR3_LASTFM_SCROBBLE_IMPORT_STOP_ON_DAILY_LIMIT=true
TR3_LASTFM_SCROBBLE_IMPORT_SEND_RETRY_CSV=true
TR3_LASTFM_SCROBBLE_IMPORT_SEND_REMAINING_CSV=true
```

Não use `TR3_SPOTIFY_CLIENT_ID` nem `TR3_SPOTIFY_CLIENT_SECRET` para Last.fm. O código reaproveita apenas o padrão de configuração e o timeout HTTP global; a escrita no Last.fm precisa de credenciais Last.fm próprias.
