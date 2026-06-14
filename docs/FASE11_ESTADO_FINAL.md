# FASE 11 — ESTADO FINAL CONSOLIDADO APÓS ETAPA 26

## Separação final do produto

A Fase 11 ficou organizada em duas superfícies:

- **/show** é o Owner Center completo. Fica na DM do owner/maestro e concentra configuração, diagnóstico, DDX, logs, música automática, catálogo, bloqueios, limites, exceções e segurança.
- **Painel do Moderador** é operacional e simples. Serve para atuar no grupo atual com três abas: Mensagens, Pessoas e Música.

O termo visível para delegação é **Moderador**. Os nomes internos `governante_*` permanecem no código por compatibilidade com tabelas, testes e rotas já criadas.

## Painel do Moderador

O painel não deve ser Owner Center. Ele deve mostrar apenas:

1. **Mensagens**
   - postar texto;
   - postar foto por URL HTTPS ou file_id com legenda;
   - apagar mensagem por link;
   - fixar/desfixar quando liberado.

2. **Pessoas**
   - silenciar/liberar;
   - banir/reintegrar;
   - convite rápido com solicitação de entrada.

3. **Música**
   - enviar música atual do moderador no grupo atual.

Se o grupo atual não for resolvido automaticamente, o painel deve listar grupos disponíveis por nome/foto. Se houver apenas um grupo possível, deve abrir direto nele.

## /show Owner Center

O `/show` concentra:

- escolher grupo;
- configurar moderadores;
- pacotes e ações;
- limites;
- exceções 24h;
- DDX;
- logs;
- diagnóstico;
- segurança;
- música automática;
- catálogo manual;
- bloqueios de artista/faixa;
- agendamentos musicais.

DDX, logs, segurança, catálogo, agendamentos, bloqueios e configuração de moderadores ficam fora do painel operacional.

## Segurança consolidada

- `/equalizador` sem sessão válida não entrega painel operacional completo.
- Backend valida sessão, perfil, grupo, pacote, ação, limite e permissão real do bot.
- Ações sensíveis exigem confirmação backend.
- HTML/JS/IDs têm guard estático.
- Callbacks do `/show` são validados por allowlist.
- Entrada DDX digitada é limitada e rejeita HTML bruto.
- URLs públicas do player são filtradas para `http/https`.

## Escopo fora do Moderador

Ficam com owner/maestro:

- DDX;
- logs/histórico;
- tópicos/fóruns;
- rádio legado;
- Multimídia nativa;
- apagar lote;
- exportar link primário;
- edição/revogação de convites antigos;
- reações/canais remetentes até existir UI segura própria;
- kick.

## Observações de compatibilidade

O código interno ainda mantém nomes históricos como `governante_scope`, `eq_governante_*` e `membros.remover`. Esses nomes são compatibilidade interna; a interface deve exibir **Moderador** e **Banir membro**.

O item `ddx.temporario` fica como legado para dados antigos e não deve ser usado para novas configurações.

## Validação antes de deploy

Antes do deploy real, aplicar o ZIP completo mais recente no repositório real, instalar `requirements.txt`, rodar os checks, subir para GitHub e testar no Telegram/Railway.
