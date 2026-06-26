"""Entidades de domínio.

São modelos puros (Pydantic), sem conhecimento de banco, canal ou IA.
Representam o contrato de negócio compartilhado entre serviços, persistência
e canais. `id` é Optional: None antes de persistido, preenchido pelo repositório.
"""
from datetime import date as date_type, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Channel(str, Enum):
    """Canais de mensagem suportados. Telegram hoje; WhatsApp depois."""

    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"


class Role(str, Enum):
    """Papel de um usuário dentro de uma organização."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class ExpenseStatus(str, Enum):
    """Ciclo de vida de um gasto (rascunho → reembolso, Fase 2).

    PENDING_REVIEW: extraído pela IA/digitado, aguardando confirmação do autor.
    SUBMITTED: confirmado pelo autor, aguardando decisão de um aprovador.
    APPROVED: aprovado por um aprovador (admin/owner da org).
    REJECTED: rejeitado — exige comentário (`decision_comment`).
    REIMBURSED: reembolsado ao autor (estado final).

    Um gasto confirmado por quem já é aprovador (uso pessoal / admin) vai direto
    para APPROVED; de um membro comum, vai para SUBMITTED até alguém decidir.
    """

    PENDING_REVIEW = "pending_review"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    REIMBURSED = "reimbursed"


class Organization(BaseModel):
    id: Optional[int] = None
    name: str
    join_code: Optional[str] = Field(
        default=None, description="Código de convite para entrar na org (`/entrar <código>`)"
    )
    created_at: Optional[datetime] = None


class User(BaseModel):
    id: Optional[int] = None
    name: str
    active_org_id: Optional[int] = Field(
        default=None, description="Org em que os gastos deste usuário são lançados"
    )
    created_at: Optional[datetime] = None


class ChannelIdentity(BaseModel):
    """Vínculo entre um usuário interno e sua identidade em um canal.

    Um mesmo `user_id` pode ter várias identidades (Telegram + WhatsApp).
    O domínio nunca referencia `telegram_id` diretamente — sempre `user_id`.
    """

    id: Optional[int] = None
    user_id: int
    channel: Channel
    external_id: str
    created_at: Optional[datetime] = None


class Membership(BaseModel):
    id: Optional[int] = None
    org_id: int
    user_id: int
    role: Role = Role.MEMBER
    created_at: Optional[datetime] = None


class Category(BaseModel):
    id: Optional[int] = None
    org_id: int
    name: str


class CostCenter(BaseModel):
    """Centro de custo definido pela organização (base para reembolso/relatórios)."""

    id: Optional[int] = None
    org_id: int
    name: str


class Expense(BaseModel):
    """Gasto. Sempre referencia `org_id` e `user_id` internos (nunca o id de canal)."""

    id: Optional[int] = None
    org_id: int
    user_id: int
    store_name: str = Field(description="Nome do estabelecimento ou loja")
    total_amount: float = Field(description="Valor total da compra")
    category: str = Field(description="Categoria do gasto")
    date: date_type = Field(description="Data da compra")
    payment_method: Optional[str] = Field(
        default=None, description="Método de pagamento (Crédito, Débito, Pix)"
    )
    status: ExpenseStatus = ExpenseStatus.PENDING_REVIEW
    receipt_url: Optional[str] = Field(
        default=None, description="Referência ao comprovante armazenado"
    )
    cost_center: Optional[str] = Field(
        default=None, description="Centro de custo (base para reembolso/aprovação)"
    )
    approver_id: Optional[int] = Field(
        default=None, description="Usuário que aprovou/rejeitou (user_id interno)"
    )
    decision_comment: Optional[str] = Field(
        default=None, description="Comentário da decisão — obrigatório na rejeição"
    )
    decided_at: Optional[datetime] = Field(
        default=None, description="Quando o gasto foi aprovado/rejeitado/reembolsado"
    )
    created_at: Optional[datetime] = None
