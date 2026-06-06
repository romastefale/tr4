# Equalizador — Release operacional

Data de consolidação: 2026-06-05

Este documento fecha a Fase 8 original e foi atualizado na Fase 54.8 para o pacote final do Equalizador em janelas. Ele não adiciona novo poder operacional; organiza a implantação segura do Equalizador já criado nas fases anteriores.

## Escopo fechado

O Equalizador deve ir para produção com estas condições:

- TR4 musical continua funcionando sem depender do Equalizador.
- `/healthz` permanece leve e não depende do Telegram.
- `/readyz` mostra banco, webhook/Telegram e hardening do Equalizador.
- `/equalizador` só existe quando `TR4_EQUALIZADOR_ENABLED=true`.
- Nenhum botão público, comando público ou menu público aponta para o Equalizador.
- A interface usa `usr_ref`, `grp_ref`, `msg_ref` e `alvo_ref`; IDs técnicos continuam internos.
- Ações operacionais só rodam com canal concedido, direito real do bot e histórico sanitizado.

## Variáveis finais

### Obrigatórias do TR4 musical

```text
TR3_TELEGRAM_BOT_TOKEN=
TR3_BASE_URL=https://SEU-DOMINIO.railway.app
TR3_DATABASE_URL=sqlite:////app/data/app.db
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
LASTFM_API_KEY=
```

### Equalizador desligado

Use este estado para deploy inicial ou rollback lógico:

```text
TR4_EQUALIZADOR_ENABLED=false
TR4_EQUALIZADOR_APP_NAME=equalizador
TR4_EQUALIZADOR_MAESTRO_IDS=
TR4_EQUALIZADOR_OPERADOR_IDS=
TR4_EQUALIZADOR_PALCO_IDS=
TR4_EQUALIZADOR_CANAIS=
TR4_EQUALIZADOR_HIDE_TECHNICAL_IDS=true
TR4_EQUALIZADOR_INITDATA_MAX_AGE_SECONDS=600
TR4_EQUALIZADOR_SESSION_TTL_SECONDS=28800
TR4_EQUALIZADOR_RATE_LIMIT_PER_MINUTE=30
```

### Equalizador ligado para Maestro

Substitua os exemplos pelos IDs reais no ambiente do servidor. Não coloque esses IDs em README, prints públicos ou interface.

```text
TR4_EQUALIZADOR_ENABLED=true
TR4_EQUALIZADOR_APP_NAME=equalizador
TR4_EQUALIZADOR_MAESTRO_IDS=8505890439
TR4_EQUALIZADOR_OPERADOR_IDS=8505890439
TR4_EQUALIZADOR_PALCO_IDS=-1001111111111,-1002222222222
TR4_EQUALIZADOR_CANAIS=8505890439:*:*
TR4_EQUALIZADOR_HIDE_TECHNICAL_IDS=true
TR4_EQUALIZADOR_INITDATA_MAX_AGE_SECONDS=600
TR4_EQUALIZADOR_SESSION_TTL_SECONDS=28800
TR4_EQUALIZADOR_RATE_LIMIT_PER_MINUTE=30
```

### Exemplo de operador delegado

```text
TR4_EQUALIZADOR_OPERADOR_IDS=8505890439,123456789
TR4_EQUALIZADOR_CANAIS=8505890439:*:*;123456789:-1001111111111:palco.ver,canais.ver,historico.ver,mensagens.apagar,membros.silenciar,membros.liberar
```

Canais críticos continuam restritos ao Maestro mesmo quando um operador delegado recebe `*`.


## Complemento Fase 54.8

A Fase 54 reorganiza o Equalizador em janelas operacionais: Início, Perfil do grupo, Mensagens, Pessoas, Convites, Tópicos, Transmissão, Diagnóstico, Histórico e Configuração.

O teste final no Railway deve ser feito somente depois de aplicar o pacote consolidado e conferir os logs reais. Antes do teste, valide que o banco antigo continua apontado no volume persistente. Se o TR3 usava `/app/data/app.db`, mantenha `TR3_DATABASE_URL=sqlite:////app/data/app.db`. Se usava outro arquivo, aponte exatamente para esse arquivo.

Canais adicionados no ciclo 54:

```text
mensagens.enviar
grupo.foto
grupo.foto.remover
```

Quando usar `TR4_EQUALIZADOR_CANAIS=MAESTRO_ID:*:*`, esses canais já ficam incluídos. Para operador delegado sem `*`, adicione apenas o necessário.

## Configuração no Telegram

1. Configure o Mini App do bot no BotFather com o nome público `equalizador`.
2. Aponte a URL do Mini App para `https://SEU-DOMINIO/equalizador`.
3. Use o direct link `https://t.me/SEU_BOT/equalizador` ou `https://t.me/SEU_BOT/equalizador?startapp=mesa`.
4. Não adicione botão público no `/start`.
5. Não registre comando público para o Equalizador.

O backend continua sendo a autoridade. O frontend apenas envia `Telegram.WebApp.initData` em `Authorization: tma <initData>` e renderiza o que o backend retornar.

## Configuração no Railway

1. Use o start command já previsto pelo projeto:

```bash
python -m app.bootstrap
```

2. O app escuta `0.0.0.0` e a variável `PORT` injetada pelo ambiente.
3. Configure o healthcheck path como:

```text
/healthz
```

4. Use volume persistente montado em:

```text
/app/data
```

5. Use SQLite dentro do volume:

```text
TR3_DATABASE_URL=sqlite:////app/data/app.db
```

6. Defina variáveis pelo painel ou Raw Editor, sempre uma por linha no formato `KEY=VALUE`.

## Validação antes do deploy

Execute localmente ou no Termux com dependências instaladas:

```bash
python -m compileall app scripts tests
PYTHONPATH=. python scripts/equalizador_release_check.py --strict
PYTHONPATH=. python scripts/smoke_imports.py
PYTHONPATH=. pytest -q
```

Se o ambiente ainda não tiver dependências, instale primeiro:

```bash
python -m pip install -r requirements.txt
```

## Smoke test pós-deploy

Com `TR4_EQUALIZADOR_ENABLED=false`:

```bash
curl -i https://SEU-DOMINIO/healthz
curl -i https://SEU-DOMINIO/readyz
curl -i https://SEU-DOMINIO/equalizador
```

Critério esperado:

- `/healthz` retorna 200.
- `/readyz` retorna 200 quando bot, banco e webhook estiverem prontos; 503 se Telegram ainda não subiu.
- `/equalizador` retorna 404 quando desligado.

Com `TR4_EQUALIZADOR_ENABLED=true`:

```bash
curl -i https://SEU-DOMINIO/healthz
curl -i https://SEU-DOMINIO/readyz
curl -i https://SEU-DOMINIO/equalizador
curl -i https://SEU-DOMINIO/equalizador/api/me
```

Critério esperado:

- `/equalizador` retorna HTML.
- `/equalizador/api/me` sem `Authorization` retorna 401.
- O Mini App dentro do Telegram deve carregar com `initData` válido.
- Operador fora das variáveis recebe tela neutra.
- Operador autorizado recebe alias e canais sem ID numérico.

## Verificação de logs

Procure apenas estes padrões seguros:

```text
EQUALIZADOR_AJUSTE_OK | ator=usr_... | palco=grp_... | ajuste=...
EQUALIZADOR_MAESTRO_OK | ator=usr_... | palco=grp_... | ajuste=...
```

Não deve aparecer em logs públicos:

```text
telegram_user_id
telegram_chat_id
message_id
@username
payload_tecnico_json
```

## Rollback

Rollback lógico preferencial:

```text
TR4_EQUALIZADOR_ENABLED=false
```

Depois reinicie/redeploie o serviço. Com isso, o router `/equalizador` deixa de ser registrado e o TR4 musical continua ativo.

Rollback de pacote:

1. Reaplique o ZIP da fase anterior estável.
2. Mantenha o volume `/app/data` preservado.
3. Não execute `DROP TABLE` automático.
4. Se precisar limpar tabelas `eq_*`, faça dump do SQLite antes.

## Critério de release aceito

O release só deve ser considerado pronto quando todos estes pontos forem verdadeiros:

- Deploy sobe com `/healthz` 200.
- `/readyz` mostra banco e Telegram prontos.
- Com Equalizador desligado, `/equalizador` fica inacessível.
- Com Equalizador ligado, `/equalizador/api/me` rejeita ausência de autorização.
- Mini App autenticado retorna somente aliases públicos.
- Canais por variável funcionam em negação por padrão.
- Ações leves e críticas exigem canal correto.
- Canais críticos exigem Maestro.
- Logs não exibem IDs técnicos.
- Smoke test e pytest passam no ambiente com dependências.
