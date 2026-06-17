"""Helpers para detectar se um usuário já conectou uma conta musical,
e textos padronizados para orientar quem ainda não conectou.

Usado por comandos de música (/playing, /albnow, /tnow, ...) para
mostrar a mesma orientação clara em qualquer chat, antes de tentar bater
nas APIs externas.
"""
from __future__ import annotations

from app.db.database import SessionLocal
from app.models.lastfm_profile import LastfmProfile
from app.models.spotify_token import SpotifyToken


def is_user_connected(user_id: int) -> bool:
    """True se o usuário tem uma conexão musical vinculada ao bot."""
    with SessionLocal() as db:
        has_spotify = (
            db.query(SpotifyToken.id).filter_by(user_id=user_id).first() is not None
        )
        if has_spotify:
            return True
        has_lastfm = (
            db.query(LastfmProfile.user_id).filter_by(user_id=user_id).first()
            is not None
        )
        return has_lastfm


# Mensagem curta para uso em grupo: evita poluir o chat e cita só o comando.
CONNECT_HINT_GROUP = (
    "Use <code>/lastfm seu_usuario</code> para conectar seu perfil musical. "
    "Depois rode o comando de novo."
)

# Mensagem completa para uso no privado: explica a sintaxe sem citar serviço musical.
CONNECT_HINT_PRIVATE = (
    "🎧 <b>Como conectar seu perfil musical:</b>\n"
    "Use <code>/lastfm seu_usuario</code> (sem @).\n\n"
    "Depois rode o comando de novo."
)


def connect_hint_for(chat_type: str | None) -> str:
    """Devolve o texto de orientação apropriado para o tipo de chat."""
    return CONNECT_HINT_PRIVATE if chat_type == "private" else CONNECT_HINT_GROUP
