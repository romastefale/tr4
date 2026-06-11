# Fase 11 — Etapa 3 — Web App governante

## Objetivo

Implementar a primeira base funcional do Web App governante, mantendo o escopo decidido:

- Web App apenas governante;
- ações unitárias;
- sem username operacional;
- sem kick;
- sem lote como fluxo novo;
- owner continua definindo o que aparece nas etapas posteriores.

## O que entrou nesta etapa

1. Pacotes declarativos do Web App:
   - Básico: postagem de texto, postagem de foto com legenda e broadcast musical futuro.
   - Moderador: Básico + apagar mensagem, ban/unban e convite único.
   - Avançado: Moderador + futuras ações como limpar reação.

2. Postagem de foto com legenda:
   - nova ação `mensagens.enviar_foto`;
   - novo endpoint `/api/palcos/{grp_ref}/mensagens/enviar-foto`;
   - usa `sendPhoto`;
   - legenda limitada a 1024 caracteres;
   - registra `msg_ref` após envio;
   - pode fixar depois do envio se operador e bot tiverem permissão.

3. Postagem e fixação:
   - se `fixar=true`, o backend exige também canal `fixados.criar`;
   - a fixação ainda valida direito real do bot (`can_pin_messages`).

4. Ban/unban:
   - ban continua via `membros.remover`;
   - `revoke_messages` agora é sempre `true` no payload gerado pelo backend;
   - link de mensagem pode resolver autor apenas quando o bot já viu/capturou o autor da mensagem.

5. Mensagens com autor conhecido:
   - `eq_mensagens` passa a ter `autor_ref` opcional;
   - captura de mensagens do bot registra autor quando disponível;
   - mensagem sem autor conhecido não pode virar alvo de ban automaticamente.

6. Resolver membro no painel:
   - username deixa de ser entrada operacional no endpoint do painel;
   - aceita ID numérico, `usr_...` ou link de mensagem conhecida.

7. Convite único com solicitação:
   - criação de convite no Web App força `solicitar_aprovacao=true` e `limite_membros=0` no payload do painel.

## Limites conhecidos

- Esta etapa ainda não implementa persistência de liberação por governante/grupo/pacote. Isso fica para etapa posterior.
- Ban por link só funciona quando o bot já capturou a autoria da mensagem. A Bot API não permite buscar autor arbitrário de mensagem antiga apenas pelo link.
- Broadcast musical e DDX não foram implementados nesta etapa.
