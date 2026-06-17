# TR4 Music Only + Web Music Stage 2

Etapa de ampliação da conexão entre a interface web musical e o código musical limpo.

## Conectado nesta etapa

- `GET /player`: serve a interface web musical preservada.
- `GET /api/public/ping`: health simples da interface.
- `POST /api/client-error`: log sanitizado de eventos JS.
- `GET /api/public/me`: valida `Telegram.WebApp.initData` via `Authorization: tma <initData>`.
- `GET /api/public/home`: retorna usuário, grupos em comum e preview de música atual.
- `GET /api/public/playing-preview`: preview de música atual.
- `POST /api/public/nowp`: executa o fluxo real do `/nowp`.
- `POST /api/public/group-command`: conecta `nowp`, `weekfm`, `monthfm`, `tcanvas`, `tly`, `tnow` e `songcharts`.
- `POST /api/public/story-command`: conecta `tstory` para DM ou grupo escolhido.
- `POST /api/public/dm-command`: conecta `albnow`, `playing` e `radiofm` em DM.
- `POST /api/public/execute-command` e `send-command-copy`: roteiam para os mesmos executores musicais permitidos.

## Segurança

- Não aceita `eqs` como autenticação final.
- Não importa pacote externo fora do escopo musical.
- Não cria tela de controle de grupo nem comandos fora do escopo musical.
- Revalida usuário e grupo com `get_chat_member` antes de publicar em grupo.
- Usa whitelist fechada de comandos musicais.

## Fonte da verdade

A interface web não recria cards nem respostas. Ela chama funções/handlers do código musical já existente, usando uma camada adaptadora que simula a entrada do comando e preserva o envio real pelo Telegram.


## Songcharts universal

Todos os usuários importados em `lastfm_profiles` entram automaticamente no ranking universal. O mosaico `/tnow` usa a união de `spotify_tokens` e `lastfm_profiles`.
