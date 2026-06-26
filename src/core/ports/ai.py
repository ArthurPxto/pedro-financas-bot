"""Port de extração de gastos a partir de imagem (multimodal)."""
from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel


class ExtractedExpense(BaseModel):
    """Resultado cru da extração pela IA.

    Ainda não é um `Expense` de domínio: não tem org/usuário e a data vem como
    string `DD/MM/YYYY` (o serviço faz o parse e monta a entidade). Esse limite
    string→date é deliberado e fica no serviço.
    """

    store_name: str
    total_amount: float
    category: str
    date: str  # DD/MM/YYYY
    payment_method: Optional[str] = None


class ExpenseExtractor(ABC):
    """Extrai dados estruturados de um gasto a partir dos bytes de uma imagem."""

    @abstractmethod
    async def extract(
        self,
        image: bytes,
        mime_type: str = "image/jpeg",
        categories: Optional[list[str]] = None,
    ) -> ExtractedExpense:
        """Extrai o gasto. Se `categories` for dada, a IA deve **sugerir** uma
        categoria dentro dessa lista (definida pela org) em vez de inventar uma."""
