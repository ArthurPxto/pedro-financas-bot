"""Modelos ORM (SQLAlchemy) — detalhe de adapter, separado das entidades de domínio.

A tradução ORM ⇄ entidade de domínio acontece nos repositórios. As entidades
em `core/entities.py` permanecem puras.
"""
from datetime import date, datetime

from enum import Enum as PyEnum

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from src.core.entities import Channel, ExpenseStatus, Role


def _enum(py_enum: type[PyEnum], name: str) -> SAEnum:
    """Coluna enum nativa do Postgres que armazena o `.value` (minúsculo),
    não o nome do membro. Mantém o banco alinhado com a serialização de domínio/JSON
    (a futura API web usa `.value`) e com SQL escrito à mão."""
    return SAEnum(py_enum, name=name, values_callable=lambda e: [m.value for m in e])


class Base(DeclarativeBase):
    pass


class OrganizationModel(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    join_code: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    # Sem FK rígida para evitar dependência circular de criação (usuário ⇄ org pessoal).
    active_org_id: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    identities: Mapped[list["ChannelIdentityModel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ChannelIdentityModel(Base):
    __tablename__ = "channel_identities"
    __table_args__ = (
        UniqueConstraint("channel", "external_id", name="uq_channel_external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    channel: Mapped[Channel] = mapped_column(_enum(Channel, "channel_enum"))
    external_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[UserModel] = relationship(back_populates="identities")


class MembershipModel(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_org_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[Role] = mapped_column(_enum(Role, "role_enum"), default=Role.MEMBER)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CategoryModel(Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_org_category_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))


class CostCenterModel(Base):
    __tablename__ = "cost_centers"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_org_cost_center_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))


class ExpenseModel(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    store_name: Mapped[str] = mapped_column(String(255))
    total_amount: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String(255))
    date_at: Mapped[date] = mapped_column()
    payment_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[ExpenseStatus] = mapped_column(
        _enum(ExpenseStatus, "expense_status_enum"),
        default=ExpenseStatus.PENDING_REVIEW,
    )
    receipt_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    cost_center: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
