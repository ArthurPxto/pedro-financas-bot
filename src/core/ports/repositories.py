"""Ports de persistência: repositórios + unidade de trabalho.

O núcleo enxerga apenas estas interfaces. A implementação concreta (SQLAlchemy
sobre Postgres) vive em `src/adapters/persistence/`.
"""
from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

from src.core.entities import (
    Category,
    Channel,
    ChannelIdentity,
    CostCenter,
    Expense,
    Membership,
    Organization,
    User,
)


class UserRepository(ABC):
    @abstractmethod
    async def get_by_channel_identity(
        self, channel: Channel, external_id: str
    ) -> Optional[User]:
        ...

    @abstractmethod
    async def get(self, user_id: int) -> Optional[User]:
        ...

    @abstractmethod
    async def add(self, user: User) -> User:
        ...

    @abstractmethod
    async def add_channel_identity(self, identity: ChannelIdentity) -> ChannelIdentity:
        ...

    @abstractmethod
    async def get_channel_identity(
        self, user_id: int, channel: Channel
    ) -> Optional[ChannelIdentity]:
        """Identidade do usuário no canal (para push). None se ele não usa o canal."""

    @abstractmethod
    async def set_active_org(self, user_id: int, org_id: int) -> None:
        ...


class OrganizationRepository(ABC):
    @abstractmethod
    async def add(self, org: Organization) -> Organization:
        ...

    @abstractmethod
    async def get(self, org_id: int) -> Optional[Organization]:
        ...

    @abstractmethod
    async def get_primary_for_user(self, user_id: int) -> Optional[Organization]:
        """Org principal de um usuário (a mais antiga em que ele é membro)."""

    @abstractmethod
    async def get_by_join_code(self, join_code: str) -> Optional[Organization]:
        ...

    @abstractmethod
    async def list_for_user(self, user_id: int) -> list[Organization]:
        ...


class MembershipRepository(ABC):
    @abstractmethod
    async def add(self, membership: Membership) -> Membership:
        ...

    @abstractmethod
    async def get(self, org_id: int, user_id: int) -> Optional[Membership]:
        ...

    @abstractmethod
    async def list_for_org(self, org_id: int) -> list[Membership]:
        """Todos os vínculos de uma org (usado para achar aprovadores)."""


class CategoryRepository(ABC):
    @abstractmethod
    async def add(self, category: Category) -> Category:
        ...

    @abstractmethod
    async def list_for_org(self, org_id: int) -> list[Category]:
        ...


class CostCenterRepository(ABC):
    @abstractmethod
    async def add(self, cost_center: CostCenter) -> CostCenter:
        ...

    @abstractmethod
    async def list_for_org(self, org_id: int) -> list[CostCenter]:
        ...


class ExpenseRepository(ABC):
    @abstractmethod
    async def add(self, expense: Expense) -> Expense:
        ...

    @abstractmethod
    async def get(self, expense_id: int) -> Optional[Expense]:
        ...

    @abstractmethod
    async def update(self, expense: Expense) -> Expense:
        ...

    @abstractmethod
    async def delete(self, expense_id: int) -> None:
        ...

    @abstractmethod
    async def list_recent(self, org_id: int, user_id: int, limit: int = 5) -> list[Expense]:
        ...

    @abstractmethod
    async def sum_since(self, org_id: int, user_id: int, since: date) -> float:
        ...

    @abstractmethod
    async def list_pending_for_org(self, org_id: int) -> list[Expense]:
        """Gastos SUBMITTED da org — a fila de aprovação."""

    @abstractmethod
    async def list_for_reimbursements(
        self, org_id: int, user_id: int, limit: int = 10
    ) -> list[Expense]:
        """Gastos do usuário já submetidos (qualquer estado de reembolso), recentes."""


class UnitOfWork(ABC):
    """Transação que agrupa os repositórios.

    Usado como async context manager. Sai com commit no sucesso, rollback em
    exceção (a implementação define o comportamento exato).
    """

    users: UserRepository
    organizations: OrganizationRepository
    memberships: MembershipRepository
    expenses: ExpenseRepository
    categories: CategoryRepository
    cost_centers: CostCenterRepository

    @abstractmethod
    async def __aenter__(self) -> "UnitOfWork":
        ...

    @abstractmethod
    async def __aexit__(self, exc_type, exc, tb) -> None:
        ...

    @abstractmethod
    async def commit(self) -> None:
        ...

    @abstractmethod
    async def rollback(self) -> None:
        ...
