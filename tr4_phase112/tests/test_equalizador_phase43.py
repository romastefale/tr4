
import importlib
import pytest


def test_phase43_permissions_include_entries_and_invites():
    permissions = importlib.import_module("app.equalizador.permissions")
    codes = {item.codigo for item in permissions.CANAL_DEFINITIONS}
    assert "entradas.aprovar" in codes
    assert "entradas.recusar" in codes
    assert "convites.editar" in codes
    assert "convites.revogar" in codes


def test_phase43_entradas_module_smoke():
    pytest.importorskip("sqlalchemy")
    entradas = importlib.import_module("app.equalizador.entradas")
    assert callable(entradas.register_join_request)
    assert callable(entradas.list_join_requests_publicos)
    assert callable(entradas.list_invites_publicos)


def test_phase43_router_exposes_expected_routes():
    pytest.importorskip("sqlalchemy")
    router = importlib.import_module("app.equalizador.router")
    html = router._EQUALIZADOR_HTML
    assert "entrada_select" in html
    assert "convite_select" in html
    assert "entradas/aprovar" in html
    assert "convites/revogar" in html
