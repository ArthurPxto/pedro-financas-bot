"""Ports de persistência: repositórios + unidade de trabalho.

O núcleo enxerga apenas estas interfaces. A implementação concreta (SQLAlchemy
sobre Postgres) vive em `src/adapters/persistence/`.
"""
from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

from src.core.entities import (
    Channel,
    ChannelIdentity,
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
    async def add(self, user: User) -> User:
        ...

    @abstractmethod
    async def add_channel_identity(self, identity: ChannelIdentity) -> ChannelIdentity:
        ...


class OrganizationRepository(ABC):
    @abstractmethod
    async def add(self, org: Organization) -> Organization:
        ...

    @abstractmethod
    async def get_primary_for_user(self, user_id: int) -> Optional[Organization]:
        """Org principal de um usuário (a mais antiga em que ele é membro).

        Na Fase 0 cada usuário tem uma única org pessoal; multi-org chega depois.
        """


class MembershipRepository(ABC):
    @abstractmethod
    async def add(self, membership: Membership) -> Membership:
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


class UnitOfWork(ABC):
    """Transação que agrupa os repositórios.

    Usado como async context manager. Sai com commit no sucesso, rollback em
    exceção (a implementação define o comportamento exato).
    """

    users: UserRepository
    organizations: OrganizationRepository
    memberships: MembershipRepository
    expenses: ExpenseRepository

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
