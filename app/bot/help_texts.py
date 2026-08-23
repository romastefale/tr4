"""Textos de /start e /help alinhados aos comandos públicos."""
from __future__ import annotations

from aiogram.types import Message


def build_start_text(message: Message, *, is_owner: bool) -> str:
    if message.chat.type != "private":
        return (
            "♫ ♥ <b>tigraoRADIO no grupo</b>\n\n"
            "Comandos musicais para compartilhar o que está tocando, letras, "
            "mosaicos e rankings do grupo.\n\n"
            "<b>Conectar Last.fm:</b> <code>/lastfm seu_username</code>\n"
            "<b>Mostrar música atual:</b> <code>/playing</code>\n"
            "<b>Mosaico do grupo:</b> <code>/tnow</code>\n"
            "<b>Ranking do grupo:</b> <code>/songcharts</code>\n\n"
            "Use <code>/help</code> para ver os comandos disponíveis aqui."
        )

    if is_owner:
        return (
            "♫ ♥ <b>tigraoRADIO</b>\n\n"
            "Sua central musical está ativa. Use esta conversa para conectar serviços, "
            "acompanhar sua música atual, gerar cards, extratos e rankings por DM.\n\n"
            "<b>Conectar Last.fm:</b> <code>/lastfm seu_username</code>\n"
            "<b>Conectar Spotify:</b> <code>/login</code>\n"
            "<b>Música atual:</b> <code>/playing</code>\n"
            "<b>Buscar música:</b> <code>/radiofm nome da música</code>\n"
            "<b>Resumo visual:</b> <code>/tnowall</code>\n\n"
            "Use <code>/help</code> para ver os comandos disponíveis nesta conversa."
        )

    return (
        "♫ ♥ <b>Bem-vindo ao tigraoRADIO</b>\n\n"
        "Conecte seu Last.fm para acompanhar o que você está ouvindo e usar "
        "os recursos musicais do bot.\n\n"
        "<b>Conectar Last.fm:</b> <code>/lastfm seu_username</code>\n"
        "<b>Música atual:</b> <code>/playing</code>\n\n"
        "Use <code>/help</code> para ver seus comandos disponíveis."
    )


def build_help_text(message: Message, *, is_owner: bool) -> str:
    if message.chat.type != "private":
        return (
            "<b>Comandos do grupo</b>\n\n"
            "<code>/help</code> — mostra esta lista.\n"
            "<code>/lastfm</code> — conecta ou mostra seu Last.fm.\n"
            "<code>/lastfmoff</code> — remove seu Last.fm.\n"
            "<code>/playing</code> — mostra sua música atual.\n"
            "<code>/tstory</code> — monta story da música atual.\n"
            "<code>/tly</code> — envia trecho de letra da música atual.\n"
            "<code>/tnow</code> — monta o mosaico de ouvintes.\n"
            "<code>/songcharts</code> — mostra o ranking musical do grupo."
        )

    if is_owner:
        return (
            "<b>Comandos da sua DM</b>\n\n"
            "<code>/start</code> — abre a apresentação do bot.\n"
            "<code>/help</code> — mostra esta lista.\n"
            "<code>/lastfm</code> — conecta ou mostra seu Last.fm.\n"
            "<code>/lastfmoff</code> — remove seu Last.fm.\n"
            "<code>/login</code> — conecta Spotify.\n"
            "<code>/logout</code> — desconecta Spotify.\n"
            "<code>/playing</code> — mostra sua música atual.\n"
            "<code>/albnow</code> — destaca o álbum da música atual.\n"
            "<code>/tcanvas</code> — envia o Canvas Spotify da música atual.\n"
            "<code>/tstory</code> — monta story da música atual.\n"
            "<code>/tly</code> — envia trecho de letra da música atual.\n"
            "<code>/radiofm</code> — busca uma música; aceita o termo junto ou resposta depois.\n"
            "<code>/nowp</code> — envia sua música atual para um grupo em comum.\n"
            "<code>/myself</code> — abre seus extratos.\n"
            "<code>/weekfm</code> — mostra seu extrato semanal Last.fm.\n"
            "<code>/monthfm</code> — mostra seu extrato mensal Last.fm.\n"
            "<code>/tnowall</code> — monta um mosaico consolidado por DM.\n"
            "<code>/songchartsall</code> — monta ranking consolidado por DM.\n"
            "<code>/weekall</code> — monta ranking semanal consolidado por DM.\n"
            "<code>/monthall</code> — monta ranking mensal consolidado por DM."
        )

    return (
        "<b>Comandos da sua DM</b>\n\n"
        "<code>/start</code> — abre a apresentação do bot.\n"
        "<code>/help</code> — mostra esta lista.\n"
        "<code>/lastfm</code> — conecta ou mostra seu Last.fm.\n"
        "<code>/lastfmoff</code> — remove seu Last.fm.\n"
        "<code>/playing</code> — mostra sua música atual.\n"
        "<code>/tstory</code> — monta story da música atual.\n"
        "<code>/tly</code> — envia trecho de letra da música atual.\n"
        "<code>/nowp</code> — envia sua música atual para um grupo em comum."
    )
