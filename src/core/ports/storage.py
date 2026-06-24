"""Port de armazenamento de comprovantes.

Reembolso exige comprovante auditável: a imagem não pode mais ser descartada
após a extração. O núcleo guarda apenas uma referência neutra (`receipt_url`)
devolvida por este port; o backend (filesystem hoje, S3 depois) é detalhe de adapter.
"""
from abc import ABC, abstractmethod


class ReceiptStorage(ABC):
    @abstractmethod
    async def save(
        self, data: bytes, *, content_type: str = "image/jpeg", key_hint: str = ""
    ) -> str:
        """Persiste os bytes do comprovante e retorna sua referência (`receipt_url`).

        `key_hint` é uma sugestão de nome/prefixo (ex.: org/usuário) — o adapter
        garante unicidade.
        """
