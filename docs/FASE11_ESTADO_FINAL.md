# FASE 11 — ESTADO FINAL CONSOLIDADO

## Estado geral

A Fase 11 consolidou a separação entre:

- **owner/maestro**, com controle estratégico via `/show`, painel owner, DDX, logs, configuração de governantes, pacotes, limites, exceções, broadcast musical e catálogo manual;
- **governante**, com Web App operacional, unitário, limitado por pacote, grupo, ação e limite diário;
- **backend**, como fronteira real de segurança, sem confiar apenas em botão escondido.

## Entregue no acumulado

- Guard HTML/JS/IDs.
- Shell negado para `/equalizador` sem sessão válida.
- `/show` owner com navegação por botões.
- Editor visual owner no painel para governantes, pacotes, ações, limites e exceções.
- Pacotes Básico, Moderador, Avançado e Personalizado.
- Gate backend por pacote governante.
- Limite diário real com bloqueio HTTP 429.
- Exceção de 24h por ação específica.
- Aviso best-effort ao owner quando limite é atingido.
- Postagem texto/foto com legenda.
- Apagar mensagem por link.
- Ban/unban unitário.
- Convite único com solicitação.
- DDX owner-only.
- Broadcast manual owner por `/broadcast`.
- Broadcast musical governante pelo Web App no grupo autorizado.
- Broadcast automático por horários.
- Bloqueio global de artista/faixa.
- Catálogo manual de músicas do owner.
- Resumo diário consolidado de limites.
- Auditoria corretiva final de JS/HTML/Python.

## Fora do escopo governante

- Logs e histórico.
- DDX.
- Entradas.
- Tópicos/fóruns.
- Rádio legado.
- Multimídia nativa.
- Apagar lote.
- Exportar link primário.
- Kick.

## Observações finais

O código interno ainda mantém nomes históricos como `membros.remover` por compatibilidade, mas o rótulo operacional correto é **Banir membro**.

O item `ddx.temporario` fica como legado para dados antigos, mas não deve ser usado para novas configurações no escopo atual.

Antes do deploy real, deve ser feita validação no ambiente completo com dependências instaladas e teste real no Telegram/Railway.

## Atualização Etapa 17

A auditoria ampliada identificou que algumas ações estavam liberáveis em pacote governante, mas dependiam de listagens ou referências owner-only. Para evitar capacidade sem caminho visual seguro, a Etapa 17 voltou a tratar reações, canais remetentes e edição/revogação de convites como recursos owner/maestro até que haja uma UI governante própria para eles.

O pacote governante atual permanece operacional: postagem, foto com legenda, apagar por link, fixar/desfixar, silenciar/liberar, banir/reintegrar, criar convite com solicitação e broadcast musical do governante.



## Etapa 19 — Segurança de entrada e callbacks

- Endureceu pontos de `innerHTML` restantes com `escapeHtml`.
- Validou URLs públicas do player antes de usar em atributos HTML.
- Limitou payload de `/api/client-error`.
- Adicionou allowlist para `callback_data` do `/show`.
- Impediu gravação de grupo/governante inexistente no estado do FSM.
- Limitou palavra/frase DDX digitada antes de persistir.
