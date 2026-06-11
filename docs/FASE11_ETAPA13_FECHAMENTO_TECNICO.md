# Fase 11 — Etapa 13 — Fechamento técnico antes do pacote final

## Objetivo

Fechar pendências técnicas antes do pacote final de aplicação/validação real:

- catálogo manual de músicas do owner;
- uso do catálogo manual no broadcast automático;
- seleção automática com menor repetição;
- fonte usada registrada com mais clareza;
- DDX controlável pelo `/show` sem expor ao governante;
- endpoints owner-only para catálogo manual;
- testes de confirmação destrutiva e criação de tabelas novas.

## Implementação

### Catálogo manual musical

Foram adicionadas funções persistentes em `app/bot/music_broadcast_core.py`:

- `add_manual_music_catalog_item`;
- `list_manual_music_catalog`;
- `remove_manual_music_catalog_item`;
- `choose_manual_catalog_track`;
- `mark_manual_catalog_used`.

A tabela nova é `eq_music_broadcast_catalog`.

O item do catálogo exige artista, música e capa/card. O broadcast automático usa o catálogo como fonte prioritária, rejeita artista/faixa bloqueados e evita repetir música/artista usado recentemente quando houver alternativa.

### Comandos owner

O `/broadcast` passou a aceitar:

- `/broadcast catalog`;
- `/broadcast catalog add Artista - Música | https://capa | https://spotify`;
- `/broadcast catalog delete mbcat_xxx`.

### Web App owner

A área owner de broadcast musical recebeu:

- cadastro visual de música manual;
- remoção visual de música do catálogo;
- listagem do catálogo junto de agendamentos e bloqueios.

Endpoints owner-only adicionados:

- `POST /equalizador/api/musica/broadcast/catalogo`;
- `DELETE /equalizador/api/musica/broadcast/catalogo/{catalog_ref}`.

### DDX pelo /show

O `/show` recebeu área DDX por botões:

- escolher grupo;
- abrir DDX;
- ativar/pausar DDX imediato;
- adicionar palavra/frase via próxima mensagem no privado;
- remover palavra por botão;
- ver últimas ocorrências resumidas.

DDX continua owner-only, sem aparecer no Web App governante.

## Validação

A validação desta etapa cobre:

- criação automática das tabelas novas;
- catálogo manual sendo fonte do broadcast automático;
- bloqueio global sendo respeitado;
- DDX via `/show` presente no código;
- endpoints de catálogo owner-only;
- validação HTML/JS/IDs;
- testes de confirmação destrutiva herdados da etapa anterior.
