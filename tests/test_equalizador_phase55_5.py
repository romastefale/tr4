from pathlib import Path


def test_phase55_5_radio_schedule_quiet_and_broadcast_backend_exist():
    radio = Path("app/equalizador/radio.py").read_text(encoding="utf-8")
    router = Path("app/equalizador/router.py").read_text(encoding="utf-8")
    assert "eq_radio_schedules" in radio
    assert "eq_radio_quiet_policies" in radio
    assert "eq_radio_broadcasts" in radio
    assert "criar_radio_schedule" in radio
    assert "run_due_radio_schedules" in radio
    assert "executar_radio_broadcast" in radio
    assert "/radio/agendamentos" in router
    assert "/radio/silencio" in router
    assert "/radio/broadcast" in router


def test_phase55_5_new_radio_channels_are_registered():
    permissions = Path("app/equalizador/permissions.py").read_text(encoding="utf-8")
    configuracao = Path("app/equalizador/configuracao.py").read_text(encoding="utf-8")
    governanca = Path("app/equalizador/governanca.py").read_text(encoding="utf-8")
    for codigo in ("radio.agendar", "radio.quiet", "radio.broadcast"):
        assert codigo in permissions
        assert codigo in configuracao
        assert codigo in governanca


def test_phase55_5_frontend_exposes_radio_operational_windows():
    router = Path("app/equalizador/router.py").read_text(encoding="utf-8")
    for token in (
        "radio_schedule_criar",
        "radio_schedule_cancelar",
        "radio_schedules_processar",
        "radio_quiet_salvar",
        "radio_broadcast_enviar",
    ):
        assert token in router
