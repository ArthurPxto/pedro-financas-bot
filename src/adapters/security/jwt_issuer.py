"""Adapter de `TokenIssuer` usando JWT (HMAC-SHA256, PyJWT).

Confina toda dependência de `jwt` aqui. O núcleo conhece apenas o port.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

from src.core.ports.auth import TokenIssuer


class JwtTokenIssuer(TokenIssuer):
    def __init__(self, secret: str, algorithm: str = "HS256"):
        self._secret = secret
        self._alg = algorithm

    def issue(self, claims: dict, ttl_seconds: int) -> str:
        now = datetime.now(timezone.utc)
        payload = {**claims, "iat": now, "exp": now + timedelta(seconds=ttl_seconds)}
        return jwt.encode(payload, self._secret, algorithm=self._alg)

    def verify(self, token: str) -> Optional[dict]:
        try:
            return jwt.decode(token, self._secret, algorithms=[self._alg])
        except jwt.PyJWTError:
            return None
