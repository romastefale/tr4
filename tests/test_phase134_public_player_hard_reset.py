from pathlib import Path

def test_phase134_public_player_hard_reset_bootstrap():
    text = Path("app/equalizador/router.py").read_text(encoding="utf-8")
    required = [
        "player_js_started", "window.onerror", "unhandledrejection",
        "/equalizador/api/public/me", "/equalizador/api/public/home",
        "/equalizador/api/public/playing-preview", "openBotBtn",
        'id="commandGrid"', "Comandos musicais",
        '"sessao": create_equalizador_session(',
        'const BOOT_LINK = "https://t.me/tigraoRADIObot?startapp"',
        'data-command="/playing"', 'data-command="/nowp"',
        'data-command="/myself"', 'data-command="/weekfm"',
        'data-command="/monthfm"', 'data-command="/songcharts"',
    ]
    for marker in required:
        assert marker in text

def test_phase134_unhandled_name_removed():
    path = Path("app/bot/telegram.py")
    if path.exists():
        text = path.read_text(encoding="utf-8")
        assert "return UNHANDLED" not in text
