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
    """Ciclo de vida de um gasto como **item de uma nota de débito** (Fase 5).

    PENDING_REVIEW: extraído pela IA/digitado, aguardando confirmação do autor.
    CONFIRMED: confirmado pelo autor — vira uma linha da nota de débito aberta.

    A partir da Fase 5 o ciclo de reembolso (aprovação/pagamento) pertence à
    **NotaDebito**, não ao gasto: o gasto é só um item. Ver [[NotaStatus]].
    """

    PENDING_REVIEW = "pending_review"
    CONFIRMED = "confirmed"


class NotaStatus(str, Enum):
    """Ciclo de vida de uma nota de débito (o documento de reembolso mensal).

    ABERTA: recebendo itens (gastos confirmados do mês).
    FECHADA: fechada pelo autor e enviada para aprovação (pendente).
    APROVADA: aprovada por um aprovador (admin/owner).
    REJEITADA: rejeitada — exige comentário (`decision_comment`).
    PAGA: reembolsada ao autor (estado final).

    Quem já é aprovador (uso pessoal/admin) fecha a nota direto para APROVADA;
    de um membro comum, vai para FECHADA até alguém decidir.
    """

    ABERTA = "aberta"
    FECHADA = "fechada"
    APROVADA = "aprovada"
    REJEITADA = "rejeitada"
    PAGA = "paga"


class Organization(BaseModel):
    id: Optional[int] = None
    name: str
    join_code: Optional[str] = Field(
        default=None, description="Código de convite para entrar na org (`/entrar <código>`)"
    )
    # Dados fiscais da tomadora (cabeçalho da nota de débito) — Fase 5.
    cnpj: Optional[str] = None
    address: Optional[str] = None
    cep: Optional[str] = None
    created_at: Optional[datetime] = None


class User(BaseModel):
    id: Optional[int] = None
    name: str
    active_org_id: Optional[int] = Field(
        default=None, description="Org em que os gastos deste usuário são lançados"
    )
    # Dados de pagamento do emitente (rodapé da nota de débito) — Fase 5.
    cpf: Optional[str] = None
    bank_name: Optional[str] = None
    bank_agency: Optional[str] = None
    bank_account: Optional[str] = None
    pix_key: Optional[str] = None
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
    nota_id: Optional[int] = Field(
        default=None, description="Nota de débito à qual este gasto pertence (item da nota)"
    )
    created_at: Optional[datetime] = None


class NotaDebito(BaseModel):
    """Nota de débito: documento de reembolso mensal que agrupa gastos (itens).

    O autor (emitente) cobra a organização (tomadora) por gastos pagos do próprio
    bolso. Carrega o ciclo de reembolso (ver `NotaStatus`), um número sequencial
    por org (atribuído ao fechar) e a competência (mês de referência).
    """

    id: Optional[int] = None
    org_id: int
    user_id: int
    numero: Optional[int] = Field(
        default=None, description="Número sequencial por org, atribuído ao fechar a nota"
    )
    competencia: date_type = Field(description="Mês de referência (1º dia do mês)")
    status: NotaStatus = NotaStatus.ABERTA
    vencimento: Optional[date_type] = Field(
        default=None, description="Vencimento (5º dia útil do mês seguinte), definido ao fechar"
    )
    outras_retencoes: float = Field(default=0.0, description="Retenções/descontos sobre o total")
    observacoes: Optional[str] = None
    approver_id: Optional[int] = Field(
        default=None, description="Usuário que aprovou/rejeitou (user_id interno)"
    )
    decision_comment: Optional[str] = Field(
        default=None, description="Comentário da decisão — obrigatório na rejeição"
    )
    decided_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
