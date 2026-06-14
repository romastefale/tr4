# FASE 11 — ETAPA 21 — Contexto automático e correção baseada em log/fontes oficiais

## Objetivo

Corrigir a confusão operacional observada no log real: o bot estava administrador com permissões, mas partes do painel ainda dependiam de seleção manual de grupo/pacote e a área musical quebrava por ausência de timezone IANA no ambiente.

## Fontes técnicas usadas

- Telegram Mini Apps: `initData` deve ser validado no servidor antes de confiar nos dados; `initDataUnsafe` não deve ser usado como fonte confiável.
- Telegram Mini Apps: `chat` aparece apenas em alguns modos; `chat_type` e `chat_instance` aparecem em direct links, mas não são `chat_id` numérico.
- Telegram Bot API: convites com `creates_join_request=True` não podem enviar `member_limit`.
- Telegram Bot API: apagar mensagem/reação depende de direitos administrativos e tem limites específicos.
- Python `zoneinfo`: se o sistema não tem base IANA e o pacote `tzdata` não está instalado, `ZoneInfo("America/Sao_Paulo")` falha.

## Correções

1. `tzdata` foi adicionado ao `requirements.txt`.
2. Pontos que usam `ZoneInfo("America/Sao_Paulo")` agora têm fallback seguro para UTC se o ambiente ainda estiver sem tzdata.
3. `TelegramWebAppIdentity` passou a preservar contexto assinado do Mini App:
   - `chat`;
   - `chat_type`;
   - `chat_instance`;
   - `start_param`.
4. A sessão curta `eqs` agora preserva esse contexto em `eq_private_sessions.context_json`.
5. Novo endpoint `/equalizador/api/contexto` resolve automaticamente o palco atual por prioridade:
   - `initData.chat.id`, quando Telegram fornece;
   - `start_param` assinado contendo `grp_...`;
   - único grupo atribuído ao operador;
   - único grupo visível.
6. O painel passa a selecionar automaticamente o grupo resolvido pelo backend antes de tentar restaurar seleção antiga.
7. A lógica não depende de campo manual livre de `id de grupo` para operar: o frontend usa o `grp_ref` público resolvido pelo servidor.

## Limitação honesta

Telegram não entrega sempre o `chat_id` numérico ao Mini App. Quando ele só entrega `chat_instance`, não há conversão oficial direta para `chat_id`. Nesses casos, o backend só pode inferir o grupo se houver `start_param` assinado, grupo único ou atribuição única.
