# Fase 11 — Etapa 22 — `/tctl` (`/tctl` legado) como Owner Center

## Decisões fechadas com o usuário

- Se o painel não descobrir o grupo automaticamente, lista grupos por nome/foto.
- Se houver só um grupo possível, abre direto nele.
- O painel do moderador terá 3 abas: **Mensagens, Pessoas e Música**.
- O termo da interface será **Moderador**.
- Owner Center fica só no /town.
- DDX fica só no /town.
- Moderador só vê **Enviar música atual**.
- A próxima fase começaria reescrevendo o `/tctl` (`/tctl` legado) FSM.

## O que esta etapa altera

Esta etapa reorganiza o `/tctl` (`/tctl` legado) para deixar de parecer uma coleção de módulos técnicos e passar a funcionar como centro do owner por objetivos:

1. Configurar moderadores.
2. Pacotes e ações.
3. Limites e exceções.
4. DDX.
5. Música.
6. Logs.
7. Diagnóstico.
8. Segurança.

A implementação mantém compatibilidade com as callbacks anteriores (`show:groups`, `show:users`, `show:packages`, `show:limits`, etc.), mas muda a apresentação para um fluxo mais claro.

## Correções de aplicabilidade

- O estado do `/tctl` (`/tctl` legado) agora tenta reaproveitar um pacote já existente quando o owner escolhe o mesmo grupo e o mesmo moderador.
- O texto exibido troca “governante” por “moderador” na superfície do owner.
- Música ganhou subpáginas de leitura: bloqueios, catálogo e agendamentos.
- Logs recentes do grupo selecionado foram levados para `/tctl` (`/tctl` legado).
- Segurança ganhou uma página de orientação objetiva para o owner.

## Fora desta etapa

- Simplificação visual do painel do moderador em 3 abas fica para a próxima etapa.
- Novos endpoints `/api/atual/...` ficam para a próxima etapa.
- Não houve deploy, GitHub ou Railway.
