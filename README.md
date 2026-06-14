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
