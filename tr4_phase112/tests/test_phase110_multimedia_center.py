from app.equalizador.multimidia import multimedia_center_public, MULTIMEDIA_KIND_LABELS


def test_phase110_supported_kind_labels_are_public_and_translated():
    assert MULTIMEDIA_KIND_LABELS["photo"] == "foto"
    assert MULTIMEDIA_KIND_LABELS["animation"] == "animação"


def test_phase110_router_has_center_endpoint():
    text = open("app/equalizador/router.py", encoding="utf-8").read()
    assert '/multimidia/centro' in text
    assert 'multimedia_center_public' in text


def test_phase110_center_payload_shape_without_rows():
    class DummyConn:
        def execute(self, *args, **kwargs):
            class R:
                def mappings(self): return self
                def all(self): return []
            return R()
    class DummyEngine:
        def begin(self): return self
        def __enter__(self): return DummyConn()
        def __exit__(self, *exc): return False
    data = multimedia_center_public(palco_ref="grp_TEST", db_engine=DummyEngine())
    assert data["resumo"]["total"] == 0
    assert any(t["tipo"] == "photo" for t in data["tipos_suportados"])
