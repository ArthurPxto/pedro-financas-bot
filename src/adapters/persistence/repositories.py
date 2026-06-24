"""Implementação SQLAlchemy dos repositórios e da UnitOfWork.

Faz a tradução entre modelos ORM e entidades de domínio. O núcleo só conhece
as interfaces em `core/ports/repositories.py`.
"""
from datetime import date
from typing import Optional

from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.adapters.persistence import models as m
from src.core.entities import (
    Channel,
    ChannelIdentity,
    Expense,
    Membership,
    Organization,
    User,
)
from src.core.ports.repositories import (
    ExpenseRepository,
    MembershipRepository,
    OrganizationRepository,
    UnitOfWork,
    UserRepository,
)


# --- Mappers ORM <-> domínio -------------------------------------------------

def _to_user(row: m.UserModel) -> User:
    return User(id=row.id, name=row.name, created_at=row.created_at)


def _to_org(row: m.OrganizationModel) -> Organization:
    return Organization(id=row.id, name=row.name, created_at=row.created_at)


def _to_expense(row: m.ExpenseModel) -> Expense:
    return Expense(
        id=row.id,
        org_id=row.org_id,
        user_id=row.user_id,
        store_name=row.store_name,
        total_amount=row.total_amount,
        category=row.category,
        date=row.date_at,
        payment_method=row.payment_method,
        status=row.status,
        receipt_url=row.receipt_url,
        cost_center=row.cost_center,
        created_at=row.created_at,
    )


# --- Repositórios ------------------------------------------------------------

class SqlAlchemyUserRepository(UserRepository):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_channel_identity(
        self, channel: Channel, external_id: str
    ) -> Optional[User]:
        stmt = (
            select(m.UserModel)
            .join(m.ChannelIdentityModel)
            .where(
                m.ChannelIdentityModel.channel == channel,
                m.ChannelIdentityModel.external_id == external_id,
            )
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_user(row) if row else None

    async def add(self, user: User) -> User:
        row = m.UserModel(name=user.name)
        self._session.add(row)
        await self._session.flush()
        return _to_user(row)

    async def add_channel_identity(self, identity: ChannelIdentity) -> ChannelIdentity:
        row = m.ChannelIdentityModel(
            user_id=identity.user_id,
            channel=identity.channel,
            external_id=identity.external_id,
        )
        self._session.add(row)
        await self._session.flush()
        return ChannelIdentity(
            id=row.id,
            user_id=row.user_id,
            channel=row.channel,
            external_id=row.external_id,
            created_at=row.created_at,
        )


class SqlAlchemyOrganizationRepository(OrganizationRepository):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, org: Organization) -> Organization:
        row = m.OrganizationModel(name=org.name)
        self._session.add(row)
        await self._session.flush()
        return _to_org(row)

    async def get_primary_for_user(self, user_id: int) -> Optional[Organization]:
        stmt = (
            select(m.OrganizationModel)
            .join(m.MembershipModel, m.MembershipModel.org_id == m.OrganizationModel.id)
            .where(m.MembershipModel.user_id == user_id)
            .order_by(m.OrganizationModel.id.asc())
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_org(row) if row else None


class SqlAlchemyMembershipRepository(MembershipRepository):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, membership: Membership) -> Membership:
        row = m.MembershipModel(
            org_id=membership.org_id,
            user_id=membership.user_id,
            role=membership.role,
        )
        self._session.add(row)
        await self._session.flush()
        return Membership(
            id=row.id,
            org_id=row.org_id,
            user_id=row.user_id,
            role=row.role,
            created_at=row.created_at,
        )


class SqlAlchemyExpenseRepository(ExpenseRepository):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, expense: Expense) -> Expense:
        row = m.ExpenseModel(
            org_id=expense.org_id,
            user_id=expense.user_id,
            store_name=expense.store_name,
            total_amount=expense.total_amount,
            category=expense.category,
            date_at=expense.date,
            payment_method=expense.payment_method,
            status=expense.status,
            receipt_url=expense.receipt_url,
            cost_center=expense.cost_center,
        )
        self._session.add(row)
        await self._session.flush()
        return _to_expense(row)

    async def get(self, expense_id: int) -> Optional[Expense]:
        row = await self._session.get(m.ExpenseModel, expense_id)
        return _to_expense(row) if row else None

    async def update(self, expense: Expense) -> Expense:
        row = await self._session.get(m.ExpenseModel, expense.id)
        if row is None:
            raise ValueError(f"Expense {expense.id} não encontrado")
        row.store_name = expense.store_name
        row.total_amount = expense.total_amount
        row.category = expense.category
        row.date_at = expense.date
        row.payment_method = expense.payment_method
        row.status = expense.status
        row.receipt_url = expense.receipt_url
        row.cost_center = expense.cost_center
        await self._session.flush()
        return _to_expense(row)

    async def delete(self, expense_id: int) -> None:
        await self._session.execute(
            sa_delete(m.ExpenseModel).where(m.ExpenseModel.id == expense_id)
        )

    async def list_recent(self, org_id: int, user_id: int, limit: int = 5) -> list[Expense]:
        stmt = (
            select(m.ExpenseModel)
            .where(
                m.ExpenseModel.org_id == org_id,
                m.ExpenseModel.user_id == user_id,
                m.ExpenseModel.status == m.ExpenseStatus.REGISTERED,
            )
            .order_by(m.ExpenseModel.date_at.desc(), m.ExpenseModel.id.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_expense(r) for r in rows]

    async def sum_since(self, org_id: int, user_id: int, since: date) -> float:
        stmt = select(func.coalesce(func.sum(m.ExpenseModel.total_amount), 0.0)).where(
            m.ExpenseModel.org_id == org_id,
            m.ExpenseModel.user_id == user_id,
            m.ExpenseModel.status == m.ExpenseStatus.REGISTERED,
            m.ExpenseModel.date_at >= since,
        )
        return float((await self._session.execute(stmt)).scalar_one())


# --- Unit of Work ------------------------------------------------------------

class SqlAlchemyUnitOfWork(UnitOfWork):
    """Abre uma sessão/transação por bloco `async with`.

    Commit explícito; rollback automático se sair com exceção.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def __aenter__(self) -> "SqlAlchemyUnitOfWork":
        self._session = self._session_factory()
        self.users = SqlAlchemyUserRepository(self._session)
        self.organizations = SqlAlchemyOrganizationRepository(self._session)
        self.memberships = SqlAlchemyMembershipRepository(self._session)
        self.expenses = SqlAlchemyExpenseRepository(self._session)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is not None:
                await self.rollback()
        finally:
            await self._session.close()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
