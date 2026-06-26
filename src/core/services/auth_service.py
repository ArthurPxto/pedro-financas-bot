"""Serviço de autenticação do painel web — neutro de canal.

Login por **magic-link enviado pelo canal já linkado** (Telegram primeiro):
o usuário pede `/login` no bot, recebe um link curto com um token de troca; o
front troca esse token por um token de sessão mais longo, usado como Bearer.

Tudo é stateless (tokens assinados, sem tabela de sessão): o bot emite num
processo e a API valida noutro, compartilhando só o segredo — nada de banco.
"""
from typing import Optional

from src.core.ports.auth import TokenIssuer

# Token de troca: curto, só serve para a primeira chamada do front.
_LOGIN_TTL = 10 * 60          # 10 min
# Token de sessão: o que o front guarda e manda como Authorization: Bearer.
_SESSION_TTL = 7 * 24 * 60 * 60  # 7 dias

_PURPOSE_LOGIN = "login"
_PURPOSE_SESSION = "session"


class AuthService:
    def __init__(self, token_issuer: TokenIssuer):
        self._tokens = token_issuer

    def create_login_token(self, user_id: int) -> str:
        """Token curto enviado pelo canal (entra no magic-link)."""
        return self._tokens.issue(
            {"sub": str(user_id), "purpose": _PURPOSE_LOGIN}, _LOGIN_TTL
        )

    def exchange(self, login_token: str) -> Optional[str]:
        """Troca o token de login por um token de sessão. None se inválido."""
        claims = self._tokens.verify(login_token)
        if not claims or claims.get("purpose") != _PURPOSE_LOGIN:
            return None
        return self._tokens.issue(
            {"sub": claims["sub"], "purpose": _PURPOSE_SESSION}, _SESSION_TTL
        )

    def verify_session(self, session_token: str) -> Optional[int]:
        """Devolve o user_id de um token de sessão válido; senão None."""
        claims = self._tokens.verify(session_token)
        if not claims or claims.get("purpose") != _PURPOSE_SESSION:
            return None
        try:
            return int(claims["sub"])
        except (KeyError, ValueError, TypeError):
            return None
