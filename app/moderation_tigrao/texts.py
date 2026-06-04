from __future__ import annotations


def home_text() -> str:
    return (
        "Tigrão — painel de moderação\n\n"
        "Escolha uma opção pelos botões abaixo.\n"
        "Todas as confirmações e erros ficam somente neste privado.\n"
        "No grupo, o bot apenas executa ações administrativas inevitáveis."
    )


def entry_text(*, is_root: bool, can_delegate: bool, can_radio: bool) -> str:
    available = []
    if is_root:
        available.append("Painel Owner")
    if can_delegate:
        available.append("Moderação delegada")
    if can_radio:
        available.append("Radio")
    options = ", ".join(available) if available else "nenhum painel disponível"
    return (
        "Tigrão — entrada de painéis\n\n"
        "Este comando agora funciona como roteador privado.\n"
        "A moderação Owner, a moderação delegada e o Radio ficam separados para reduzir mistura de poderes.\n\n"
        f"Painéis disponíveis: {options}."
    )


def owner_home_text() -> str:
    return (
        "Owner — painel administrativo\n\n"
        "Área exclusiva do Owner para moderação avançada, governança, segurança e logs.\n"
        "Personalização/postagens ficam separadas no painel Radio."
    )


def delegate_home_text() -> str:
    return (
        "Tigrão — moderação delegada\n\n"
        "Área para membros com permissões delegadas por grupo.\n"
        "Ações estruturais, segurança e governança permanecem fora deste painel."
    )


def radio_home_text() -> str:
    return (
        "Radio — painel de postagens\n\n"
        "Área separada para enviar mensagens e mídias pelo bot.\n"
        "O Owner tem acesso total; membros delegados só veem/acionam funções conforme grants radio.* por grupo.\n"
        "Nome, descrição, foto e links do grupo continuam sendo governança estrutural."
    )


def blocked_text() -> str:
    return "Acesso negado."


def error_text(title: str, detail: str, fix: str | None = None) -> str:
    text = f"Tigrão — erro\n\n{title}\n\nMotivo: {detail}"
    if fix:
        text += f"\nCorreção: {fix}"
    return text


def success_text(title: str, detail: str) -> str:
    return f"Tigrão — ação concluída\n\n{title}\n\n{detail}"
