from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_convite_depende_de_afinacao_visual():
    router = (ROOT / "app" / "equalizador" / "router.py").read_text()
    assert 'codigo === "convites.criar"' not in router
    assert 'direitosDisponiveis.has(codigo)' in router


def test_router_retorna_motivo_publico_do_mesa_error():
    router = (ROOT / "app" / "equalizador" / "router.py").read_text()
    assert "mesa_error_public_detail" in router
    assert 'detail=mesa_error_public_detail(exc)' in router
    assert 'detail="Ajuste não concluído."' not in router.split("async def _execute_action_endpoint", 1)[1].split("async def _execute_maestro_endpoint", 1)[0]


def test_mesa_tem_erro_telegram_sanitizado():
    mesa = (ROOT / "app" / "equalizador" / "mesa.py").read_text()
    assert "class MesaTelegramError" in mesa
    assert "def _safe_error_text" in mesa
    assert "raise MesaTelegramError(description)" in mesa
    assert "Telegram recusou:" in mesa
    assert "motivo_publico" in mesa


def test_interface_mostra_convite_retornado():
    router = (ROOT / "app" / "equalizador" / "router.py").read_text()
    assert "data.convite" in router
    assert "Convite criado" in router
