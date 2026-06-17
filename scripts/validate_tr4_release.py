#!/usr/bin/env python3
"""Validação local do pacote TR4 musical antes de deploy.

Não importa módulos externos do bot. O objetivo é travar o contrato das etapas finais:
perfil Telegram persistente, nome visual sem username musical, mosaico adaptativo
sem corte por grade, card sem badge de provedor e ausência de bytecode/cache no
pacote.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def fail(message: str) -> None:
    print(f"ERRO: {message}", file=sys.stderr)
    raise SystemExit(1)


def check_no_python_cache() -> None:
    bad = [p for p in ROOT.rglob("*") if p.name == "__pycache__" or p.suffix == ".pyc"]
    if bad:
        fail("pacote contém __pycache__/.pyc: " + ", ".join(str(p.relative_to(ROOT)) for p in bad[:10]))


def check_parse_and_compile() -> None:
    for path in ROOT.rglob("*.py"):
        if ".git" in path.parts:
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            fail(f"erro de sintaxe em {path.relative_to(ROOT)}: {exc}")


def check_tnow_contract() -> None:
    tnow = read("app/bot/tnow.py")
    card = read("app/services/tnow_card.py")
    profiles = read("app/services/telegram_user_profiles.py")
    database = read("app/db/database.py")

    if "selected_activities = eligible[:MAX_TILES]" not in tnow:
        fail("tnow não seleciona todos os válidos até MAX_TILES")
    if "eligible[:slots]" in tnow:
        fail("tnow ainda corta válidos pela capacidade da grade")
    if "resolve_music_display_name" not in tnow:
        fail("tnow não usa resolvedor central de nome visual")
    display_block = tnow.split("async def _display_name", 1)[1].split("async def _warm_cover_cache", 1)[0]
    if "_lastfm_display_name" in display_block or "return lastfm_username" in display_block or "str(lastfm_username).strip()" in display_block:
        fail("_display_name ainda usa username musical como fallback visual")
    if "TNOW_GRID_SELECTED" not in tnow or "empty_slots" not in tnow or "capacity" not in tnow:
        fail("log de grade não expõe capacity/empty_slots")
    if "provider-badge" in card or "last.fm" in card.lower() or "spotify" in card.lower():
        fail("card do mosaico expõe provedor musical")
    if "Uso: /tpv <ID Telegram>" in tnow or "<telegram_id>" in tnow:
        fail("/tpv ainda contém placeholder com < > que quebra parse HTML")
    if "Uso: /tpv ID_Telegram tnow|mosaico|all|off" not in tnow:
        fail("/tpv não expõe uso seguro sem tags HTML")
    if "telegram_user_profiles" not in database or "TelegramUserProfile" not in database:
        fail("banco não cria/importa telegram_user_profiles")
    if "TPV_DEFAULT_LABEL" not in profiles or "telegram_get_chat" not in profiles:
        fail("resolvedor visual não mantém /tpv e reparo via get_chat")


def check_user_facing_text_contract() -> None:
    commands = read("app/bot/setup_commands.py")
    telegram = read("app/bot/telegram.py")
    connection = read("app/services/connection_check.py")
    runner = read("app/bot/music_command_runner.py")

    if "Last.fm" in commands or "Last fm" in commands or "Spotify" in commands:
        fail("setup_commands expõe nome de serviço musical")
    hint_block = connection.split("CONNECT_HINT_GROUP", 1)[1]
    if "Last.fm" in hint_block or "Last fm" in hint_block or "Spotify" in hint_block:
        fail("connection_check expõe nome de serviço musical nas mensagens")
    if "/lastfm seu_usuario" not in telegram or "/login" not in telegram:
        fail("telegram.py não explica comandos /lastfm e /login")
    telegram_user_blocks = "\n".join(line for line in telegram.splitlines() if "message.answer" in line or "_answer_with_effect" in line or "<code>/lastfm" in line or "<code>/login" in line)
    if "Last.fm" in telegram_user_blocks or "Last fm" in telegram_user_blocks or "Spotify" in telegram_user_blocks:
        fail("telegram contém nome de serviço em blocos user-facing verificados")
    runner_messages = "\n".join(line for line in runner.splitlines() if '"message"' in line or "MusicCommandError" in line)
    if "Last.fm" in runner_messages or "Last fm" in runner_messages or "Spotify" in runner_messages:
        fail("runner contém nome de serviço em mensagens user-facing verificadas")


def check_expected_provider_failures_are_not_crashes() -> None:
    spotify = read("app/services/spotify.py")
    lastfm = read("app/services/lastfm.py")

    if 'logger.error("Spotify recent error' in spotify:
        fail("falha esperada de conta musical externa ainda é registrada como erro crítico")
    if 'logger.error("Last fm error' in lastfm:
        fail("perfil musical inexistente ainda é registrado como erro crítico")
    if "reason=user_not_registered" not in spotify or "logger.warning" not in spotify:
        fail("spotify.py não trata usuário não autorizado como indisponibilidade esperada")
    if "reason=user_not_found" not in lastfm or "logger.warning" not in lastfm:
        fail("lastfm.py não trata perfil inexistente como indisponibilidade esperada")



def check_radiofm_own_transient_flow_contract() -> None:
    radiofm = read("app/bot/radiofm.py")

    if "apaga somente essa mensagem própria" not in radiofm or "Não apaga comando do usuário" not in radiofm:
        fail("radiofm não documenta o contrato de limpar apenas mensagem própria do bot")
    if "flow_chat_id" not in radiofm or "flow_msg_id" not in radiofm:
        fail("radiofm não guarda mensagem transitória própria para edição/exclusão")
    if "async def _safe_delete_bot_message" not in radiofm or "await bot.delete_message" not in radiofm:
        fail("radiofm não possui helper seguro para apagar mensagem própria do bot")
    if "async def _set_flow_message" not in radiofm or "await bot.edit_message_text" not in radiofm:
        fail("radiofm não possui helper de edição da mensagem transitória")
    if 'await message.answer("Escolha a faixa:"' in radiofm:
        fail("radiofm ainda envia lista como nova mensagem permanente")
    if 'text="Escolha a faixa:"' not in radiofm or 'reply_markup=keyboard' not in radiofm:
        fail("radiofm não edita mensagem transitória para lista de escolhas")
    if 'text="Preparando card..."' not in radiofm:
        fail("radiofm não edita a mensagem transitória durante preparação do card")
    if "# Music-only clean: apaga somente a mensagem transitória do próprio bot." not in radiofm:
        fail("radiofm não registra limpeza final da mensagem própria")
    if "_safe_delete_bot_message(bot, flow_chat_id, flow_msg_id)" not in radiofm:
        fail("radiofm não apaga a mensagem transitória própria ao concluir o card")
    if "message.delete(" in radiofm or "delete_message(message.chat.id" in radiofm or "delete_message(chat_id=message.chat.id" in radiofm:
        fail("radiofm tenta apagar mensagem do usuário ou mensagem não rastreada como própria")
    if "command_msg_id" in radiofm.split("async def _safe_delete_bot_message", 1)[1].split("async def _resolve_spotify_output", 1)[0]:
        fail("helper de exclusão do radiofm referencia mensagem de comando do usuário")

def main() -> int:
    check_no_python_cache()
    check_parse_and_compile()
    check_tnow_contract()
    check_user_facing_text_contract()
    check_expected_provider_failures_are_not_crashes()
    check_radiofm_own_transient_flow_contract()
    print("TR4_RELEASE_VALIDATE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
