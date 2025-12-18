from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class Expense(BaseModel):
    user_id: int = Field(description="ID único do usuário do Telegram")
    store_name: str = Field(description="Nome do estabelecimento ou loja")
    total_amount: float = Field(description="Valor total da compra")
    category: str = Field(description="Categoria do gasto (ex: Alimentação, Transporte, Lazer)")
    date: str = Field(default_factory=lambda: datetime.now().strftime("%d/%m/%Y"), description="Data da compra")
    payment_method: Optional[str] = Field(description="Método de pagamento (Crédito, Débito, Pix)")

    class Config:
        schema_extra = {
            "example": {
                "store_name": "Mercado Central",
                "total_amount": 150.50,
                "category": "Alimentação",
                "date": "17/12/2023",
                "payment_method": "Crédito"
            }
        }