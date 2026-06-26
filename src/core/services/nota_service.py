"""Serviço da nota de débito — neutro de canal (Fase 5).

A nota é o documento de reembolso mensal: agrupa gastos (itens) de um autor e
carrega o ciclo `aberta → fechada → aprovada/rejeitada → paga`. Os gastos
confirmados caem na nota ABERTA do autor; ao fechar, ela ganha número e
vencimento e segue para aprovação (ou direto a aprovada, se o autor já é
aprovador — uso pessoal/admin sem fricção).
"""
from datetime import date, datetime, timedelta
from typing import Callable, Optional

from src.core.entities import Expense, NotaDebito, NotaStatus
from src.core.ports.repositories import UnitOfWork
from src.core.services.org_service import UserContext
from src.logging_config import get_logger

log = get_logger(__name__)


def first_of_month(d: date) -> date:
    return d.replace(day=1)


def fifth_business_day_next_month(competencia: date) -> date:
    """5º dia útil do mês seguinte à competência (sem considerar feriados)."""
    year, month = competencia.year, competencia.month
    year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    d = date(year, month, 1)
    business = 0
    while True:
        if d.weekday() < 5:  # seg–sex
            business += 1
            if business == 5:
                return d
        d += timedelta(days=1)


def valor_a_pagar(nota: NotaDebito, items: list[Expense]) -> float:
    return round(sum(i.total_amount for i in items) - (nota.outras_retencoes or 0.0), 2)


class NotaService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]):
        self._uow_factory = uow_factory

    # --- Autor: abrir / acompanhar -----------------------------------------

    async def ensure_open(self, ctx: UserContext, today: date) -> NotaDebito:
        """Devolve a nota ABERTA do autor; cria uma (competência = mês atual) se não houver."""
        async with self._uow_factory() as uow:
            nota = await uow.notas.get_open_for_user(ctx.org_id, ctx.user_id)
            if nota is None:
                nota = await uow.notas.add(
                    NotaDebito(
                        org_id=ctx.org_id,
                        user_id=ctx.user_id,
                        competencia=first_of_month(today),
                    )
                )
                await uow.commit()
            return nota

    async def list_for_user(self, ctx: UserContext) -> list[NotaDebito]:
        async with self._uow_factory() as uow:
            return await uow.notas.list_for_user(ctx.org_id, ctx.user_id)

    async def list_for_org(self, ctx: UserContext) -> list[NotaDebito]:
        async with self._uow_factory() as uow:
            return await uow.notas.list_for_org(ctx.org_id)

    async def current_open(self, ctx: UserContext) -> Optional[NotaDebito]:
        """Nota ABERTA do autor, sem criar uma nova (diferente de `ensure_open`)."""
        async with self._uow_factory() as uow:
            return await uow.notas.get_open_for_user(ctx.org_id, ctx.user_id)

    async def get_with_items(
        self, ctx: UserContext, nota_id: int, *, include_others: bool = False
    ) -> Optional[tuple[NotaDebito, list[Expense]]]:
        """Nota + itens. `include_others` (aprovador) permite ver notas de terceiros."""
        async with self._uow_factory() as uow:
            nota = await uow.notas.get(nota_id)
            if nota is None or nota.org_id != ctx.org_id:
                return None
            if not include_others and nota.user_id != ctx.user_id:
                return None
            items = await uow.expenses.list_for_nota(nota_id)
            return nota, items

    async def close(
        self, ctx: UserContext, nota_id: int, *, approve_directly: bool
    ) -> Optional[NotaDebito]:
        """Fecha a nota ABERTA do autor: numera, define vencimento e submete.

        Retorna None se a nota não for fechável (inexistente, de outro/já fechada)
        ou se estiver **sem itens** — o app distingue checando os itens antes.
        """
        async with self._uow_factory() as uow:
            nota = await uow.notas.get(nota_id)
            if (
                nota is None
                or nota.org_id != ctx.org_id
                or nota.user_id != ctx.user_id
                or nota.status != NotaStatus.ABERTA
            ):
                return None
            if not await uow.expenses.list_for_nota(nota_id):
                return None
            nota.numero = await uow.notas.next_numero(ctx.org_id)
            nota.vencimento = fifth_business_day_next_month(nota.competencia)
            if approve_directly:
                nota.status = NotaStatus.APROVADA
                nota.approver_id = ctx.user_id
                nota.decided_at = datetime.now()
            else:
                nota.status = NotaStatus.FECHADA
            saved = await uow.notas.update(nota)
            await uow.commit()
        log.info("nota fechada", nota_id=nota_id, status=saved.status.value)
        return saved

    # --- Aprovador (o app garante o papel antes de chamar) ------------------

    async def list_pending(self, ctx: UserContext) -> list[NotaDebito]:
        async with self._uow_factory() as uow:
            return await uow.notas.list_pending_for_org(ctx.org_id)

    async def approve(self, ctx: UserContext, nota_id: int) -> Optional[NotaDebito]:
        return await self._decide(ctx, nota_id, NotaStatus.APROVADA)

    async def reject(self, ctx: UserContext, nota_id: int, comment: str) -> Optional[NotaDebito]:
        return await self._decide(ctx, nota_id, NotaStatus.REJEITADA, comment=comment)

    async def pay(self, ctx: UserContext, nota_id: int) -> Optional[NotaDebito]:
        async with self._uow_factory() as uow:
            nota = await uow.notas.get(nota_id)
            if nota is None or nota.org_id != ctx.org_id or nota.status != NotaStatus.APROVADA:
                return None
            nota.status = NotaStatus.PAGA
            nota.decided_at = datetime.now()
            saved = await uow.notas.update(nota)
            await uow.commit()
        log.info("nota paga", nota_id=nota_id)
        return saved

    async def _decide(
        self, ctx: UserContext, nota_id: int, status: NotaStatus, *, comment: Optional[str] = None
    ) -> Optional[NotaDebito]:
        async with self._uow_factory() as uow:
            nota = await uow.notas.get(nota_id)
            # Idempotente e escopado: só decide uma nota FECHADA da org do aprovador.
            if nota is None or nota.org_id != ctx.org_id or nota.status != NotaStatus.FECHADA:
                return None
            nota.status = status
            nota.approver_id = ctx.user_id
            nota.decision_comment = comment
            nota.decided_at = datetime.now()
            saved = await uow.notas.update(nota)
            await uow.commit()
        log.info("nota decidida", nota_id=nota_id, status=status.value)
        return saved
