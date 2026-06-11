from __future__ import annotations

from dataclasses import dataclass


BASIC_ACTIONS: tuple[str, ...] = (
    "mensagens.enviar",
    "mensagens.enviar_foto",
    "broadcast.musical.webapp",
)

MODERATOR_ACTIONS: tuple[str, ...] = BASIC_ACTIONS + (
    "mensagens.apagar",
    "membros.remover",
    "membros.reintegrar",
    "convites.criar",
)

# O pacote avançado continua governante-operacional: amplia o que o owner pode
# liberar no Web App sem abrir módulos owner-only ou ações que dependem de
# listagens/refências owner-only. Reações, canais remetentes e edição/revogação
# de convites voltam ao owner até haver uma UI governante segura específica.
ADVANCED_ACTIONS: tuple[str, ...] = MODERATOR_ACTIONS + (
    "membros.silenciar",
    "membros.liberar",
    "fixados.criar",
    "fixados.remover",
)

CUSTOM_PACKAGE = "personalizado"

CUSTOM_ALLOWED_ACTIONS: tuple[str, ...] = tuple(dict.fromkeys(ADVANCED_ACTIONS))

WEBAPP_PACKAGES: dict[str, tuple[str, ...]] = {
    "basico": BASIC_ACTIONS,
    "moderador": MODERATOR_ACTIONS,
    "avancado": ADVANCED_ACTIONS,
    CUSTOM_PACKAGE: (),
}

OWNER_ONLY_ACTIONS: tuple[str, ...] = (
    "ddx.configurar",
    "ddx.logs",
    "logs.ver",
    "historico.ver",
    "historico.exportar",
    "grupo.titulo",
    "grupo.descricao",
    "grupo.foto",
    "admins.promover",
    "admins.rebaixar",
    "transmissao.enviar",
    "convites.exportar_primario",
    "radio.broadcast",
    "radio.agendar",
)

FORBIDDEN_WEBAPP_ACTIONS: tuple[str, ...] = (
    "kick",
    "mensagens.apagar_lote",
    "ddx.configurar",
    "ddx.logs",
    "logs.ver",
    "historico.ver",
    "historico.exportar",
    "entradas.aprovar",
    "entradas.recusar",
    "novos.apagar",
    "novos.silenciar",
    "novos.banir",
    "novos.ignorar",
    "topicos.criar",
    "topicos.editar",
    "topicos.fechar",
    "topicos.reabrir",
    "topicos.apagar",
    "radio.broadcast",
    "radio.agendar",
    "convites.exportar_primario",
)


@dataclass(frozen=True)
class GovernanteCapability:
    pacote: str
    action: str
    permitido: bool
    motivo: str = ""


def package_actions(pacote: str) -> tuple[str, ...]:
    return WEBAPP_PACKAGES.get(str(pacote or "").strip().lower(), ())


def custom_action_is_allowed(action: str) -> bool:
    action_value = str(action or "").strip()
    return bool(action_value and action_value in CUSTOM_ALLOWED_ACTIONS and action_value not in FORBIDDEN_WEBAPP_ACTIONS)


def sanitize_custom_actions(actions: object) -> tuple[str, ...]:
    if isinstance(actions, str):
        raw_items = [item.strip() for item in actions.replace(";", ",").split(",")]
    elif isinstance(actions, (list, tuple, set)):
        raw_items = [str(item or "").strip() for item in actions]
    else:
        raw_items = []
    clean: list[str] = []
    for item in raw_items:
        if custom_action_is_allowed(item) and item not in clean:
            clean.append(item)
    return tuple(clean)


def action_allowed_by_package(*, pacote: str, action: str) -> GovernanteCapability:
    action_value = str(action or "").strip()
    if action_value in FORBIDDEN_WEBAPP_ACTIONS:
        return GovernanteCapability(pacote=pacote, action=action_value, permitido=False, motivo="fora_do_escopo_webapp")
    actions = package_actions(pacote)
    if str(pacote or "").strip().lower() == CUSTOM_PACKAGE:
        return GovernanteCapability(pacote=pacote, action=action_value, permitido=False, motivo="pacote_personalizado_exige_actions_json")
    if not actions:
        return GovernanteCapability(pacote=pacote, action=action_value, permitido=False, motivo="pacote_indisponivel")
    if action_value not in actions:
        return GovernanteCapability(pacote=pacote, action=action_value, permitido=False, motivo="acao_nao_incluida_no_pacote")
    return GovernanteCapability(pacote=pacote, action=action_value, permitido=True)
