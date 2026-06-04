from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_equalizador_member_actions_preflight_target_state() -> None:
    source = read("app/equalizador/mesa.py")
    assert "class MesaTargetError(MesaError)" in source
    assert "async def ensure_member_target_eligible" in source
    assert '"getChatMember"' in source
    assert 'status in {"creator", "administrator"}' in source
    assert "Alvo é administrador do palco" in source
    assert "Alvo automatizado" in source
    assert 'status != "kicked"' in source


def test_equalizador_member_actions_keep_ids_internal_only() -> None:
    source = read("app/equalizador/mesa.py")
    assert 'alvo_ref = _safe_text(payload.get("alvo_ref"))' in source
    assert 'not alvo_ref.startswith("usr_")' in source
    assert '"user_id": int(target["telegram_user_id"])' in source
    assert "telegram_user_id" not in read("app/equalizador/router.py").split("<script", 1)[1]


def test_equalizador_capture_registers_new_chat_members_without_consuming_handlers() -> None:
    source = read("app/bot/telegram.py")
    assert 'getattr(message, "new_chat_members", None)' in source
    assert "register_alvo_ref" in source
    assert "return await handler(event, data)" in source


def test_equalizador_member_ui_requires_selected_target() -> None:
    source = read("app/equalizador/router.py")
    assert "Escolha um membro registrado" in source
    assert 'action.startsWith("membros.") && !alvoRef' in source
    assert 'document.getElementById("alvo_select").addEventListener("change", updateButtons)' in source
