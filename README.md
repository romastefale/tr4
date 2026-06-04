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
