"""Relatórios consolidados do painel web — neutro de canal.

Lê a **mesma** camada de persistência do bot (sem duplicar regra). Para os
volumes do MVP, busca os gastos filtrados uma vez e agrega em Python — mais
simples que vários GROUP BY e suficiente. Se o volume crescer, troca-se por
agregação no banco sem mexer na API.
"""
from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional

from pydantic import BaseModel

from src.core.entities import Expense, NotaStatus
from src.core.ports.repositories import UnitOfWork


@dataclass(frozen=True)
class ReportFilter:
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    # Filtra pelos itens cujas notas estão neste estado (ex.: aprovada/paga).
    nota_status: Optional[NotaStatus] = None
    category: Optional[str] = None
    cost_center: Optional[str] = None
    user_id: Optional[int] = None


class Bucket(BaseModel):
    """Uma fatia agregada de um relatório (ex.: total de uma categoria)."""

    key: str
    total: float
    count: int


class ReportOverview(BaseModel):
    total: float
    count: int
    by_category: list[Bucket]
    by_cost_center: list[Bucket]
    by_user: list[Bucket]
    by_month: list[Bucket]


class ReportService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]):
        self._uow_factory = uow_factory

    async def overview(self, org_id: int, flt: ReportFilter) -> ReportOverview:
        expenses = await self._fetch(org_id, flt)
        names = await self._user_names(expenses)
        return ReportOverview(
            total=round(sum(e.total_amount for e in expenses), 2),
            count=len(expenses),
            by_category=_bucketize(expenses, lambda e: e.category or "—"),
            by_cost_center=_bucketize(expenses, lambda e: e.cost_center or "Sem centro"),
            by_user=_bucketize(expenses, lambda e: names.get(e.user_id, f"usuário {e.user_id}")),
            by_month=_bucketize(expenses, lambda e: e.date.strftime("%Y-%m"), sort_by_key=True),
        )

    async def list_for_export(self, org_id: int, flt: ReportFilter) -> list[Expense]:
        return await self._fetch(org_id, flt)

    async def _fetch(self, org_id: int, flt: ReportFilter) -> list[Expense]:
        async with self._uow_factory() as uow:
            return await uow.expenses.list_filtered(
                org_id,
                date_from=flt.date_from,
                date_to=flt.date_to,
                category=flt.category,
                cost_center=flt.cost_center,
                user_id=flt.user_id,
                nota_status=flt.nota_status,
            )

    async def _user_names(self, expenses: list[Expense]) -> dict[int, str]:
        ids = {e.user_id for e in expenses}
        names: dict[int, str] = {}
        async with self._uow_factory() as uow:
            for uid in ids:
                user = await uow.users.get(uid)
                if user is not None:
                    names[uid] = user.name
        return names


def _bucketize(
    expenses: list[Expense],
    key_of: Callable[[Expense], str],
    *,
    sort_by_key: bool = False,
) -> list[Bucket]:
    """Agrupa por uma chave, somando valor e contagem.

    Ordena por chave (ex.: meses cronológicos) ou por maior total (ranking).
    """
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for e in expenses:
        k = key_of(e)
        totals[k] = totals.get(k, 0.0) + e.total_amount
        counts[k] = counts.get(k, 0) + 1
    buckets = [Bucket(key=k, total=round(v, 2), count=counts[k]) for k, v in totals.items()]
    buckets.sort(key=(lambda b: b.key) if sort_by_key else (lambda b: -b.total))
    return buckets
