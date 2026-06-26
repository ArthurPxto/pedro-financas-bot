"""Port de emissão/validação de tokens assinados.

O mecanismo concreto (JWT via PyJWT, itsdangerous, ...) é detalhe de adapter.
O núcleo só precisa emitir um token com um payload e um TTL, e validá-lo de
volta. Sem estado: a validade é carregada no próprio token (assinado), então
o bot pode emitir num processo e a API validar noutro, sem banco compartilhado.
"""
from abc import ABC, abstractmethod
from typing import Optional


class TokenIssuer(ABC):
    @abstractmethod
    def issue(self, claims: dict, ttl_seconds: int) -> str:
        """Emite um token assinado que expira em `ttl_seconds`."""

    @abstractmethod
    def verify(self, token: str) -> Optional[dict]:
        """Devolve os claims se o token for válido e não expirado; senão None."""
