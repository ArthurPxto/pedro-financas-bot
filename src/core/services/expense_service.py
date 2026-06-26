"""Serviço de gastos — neutro de canal.

Recebe comandos normalizados (não sabe o que é Telegram) e é chamado tanto
pelo bot quanto, futuramente, pela API web. Aqui mora o limite string→date
(a IA devolve `DD/MM/YYYY`; o domínio guarda um `date`).
"""
from datetime import date, datetime, timedelta
from typing import Callable, Optional

from src.core.entities import Expense, ExpenseStatus
from src.core.ports.ai import ExpenseExtractor
from src.core.ports.repositories import UnitOfWork
from src.core.ports.storage import ReceiptStorage
from src.core.services.org_service import UserContext
from src.logging_config import get_logger

log = get_logger(__name__)


class ExpenseService:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        extractor: ExpenseExtractor,
        receipt_storage: ReceiptStorage,
    ):
        self._uow_factory = uow_factory
        self._extractor = extractor
        self._receipts = receipt_storage

    async def create_draft_from_image(
        self, ctx: UserContext, image: bytes, mime_type: str = "image/jpeg"
    ) -> Expense:
        """Extrai o gasto da imagem, guarda o comprovante e cria um rascunho.

        O rascunho fica PENDING_REVIEW até o usuário confirmar — base para a
        revisão antes de salvar e para o fluxo de reembolso (comprovante auditável).
        """
        # A IA sugere a categoria dentro da lista da org (se houver), em vez de inventar.
        async with self._uow_factory() as uow:
            categories = [c.name for c in await uow.categories.list_for_org(ctx.org_id)]

        extracted = await self._extractor.extract(image, mime_type, categories=categories)

        receipt_url = await self._receipts.save(
            image,
            content_type=mime_type,
            key_hint=f"org-{ctx.org_id}/user-{ctx.user_id}",
        )

        expense = Expense(
            org_id=ctx.org_id,
            user_id=ctx.user_id,
            store_name=extracted.store_name,
            total_amount=extracted.total_amount,
            category=extracted.category,
            date=self._parse_date(extracted.date),
            payment_method=extracted.payment_method,
            status=ExpenseStatus.PENDING_REVIEW,
            receipt_url=receipt_url,
        )

        async with self._uow_factory() as uow:
            saved = await uow.expenses.add(expense)
            await uow.commit()
        log.info("draft criado", expense_id=saved.id, org_id=ctx.org_id, user_id=ctx.user_id)
        return saved

    async def create_manual_draft(
        self, ctx: UserContext, amount: float, description: str, category: str = "Outros"
    ) -> Expense:
        """Cria um rascunho a partir de texto (`/gasto`), sem comprovante.

        Nem todo gasto tem nota fotografável; passa pelo mesmo passo de revisão.
        """
        expense = Expense(
            org_id=ctx.org_id,
            user_id=ctx.user_id,
            store_name=description.strip() or "Gasto",
            total_amount=amount,
            category=category,
            date=date.today(),
            status=ExpenseStatus.PENDING_REVIEW,
        )
        async with self._uow_factory() as uow:
            saved = await uow.expenses.add(expense)
            await uow.commit()
        log.info("draft manual criado", expense_id=saved.id, org_id=ctx.org_id)
        return saved

    async def confirm(self, ctx: UserContext, expense_id: int) -> Optional[Expense]:
        """Confirma um rascunho do próprio usuário, marcando-o como registrado."""
        async with self._uow_factory() as uow:
            expense = await uow.expenses.get(expense_id)
            # Idempotente: só age sobre um rascunho do próprio usuário ainda pendente.
            # Evita confirmar duas vezes (a inline keyboard persiste após o clique).
            if not self._is_actionable_draft(ctx, expense):
                return None
            expense.status = ExpenseStatus.REGISTERED
            saved = await uow.expenses.update(expense)
            await uow.commit()
        log.info("gasto confirmado", expense_id=expense_id)
        return saved

    async def cancel(self, ctx: UserContext, expense_id: int) -> bool:
        """Descarta um rascunho do próprio usuário (apenas se ainda pendente)."""
        async with self._uow_factory() as uow:
            expense = await uow.expenses.get(expense_id)
            # Idempotente: nunca apaga um gasto já registrado via clique tardio em "cancelar".
            if not self._is_actionable_draft(ctx, expense):
                return False
            await uow.expenses.delete(expense_id)
            await uow.commit()
        log.info("rascunho cancelado", expense_id=expense_id)
        return True

    async def get_draft(self, ctx: UserContext, expense_id: int) -> Optional[Expense]:
        async with self._uow_factory() as uow:
            expense = await uow.expenses.get(expense_id)
            return expense if self._is_actionable_draft(ctx, expense) else None

    async def set_category(
        self, ctx: UserContext, expense_id: int, category: str
    ) -> Optional[Expense]:
        """Edita a categoria de um rascunho em revisão (botão inline)."""
        return await self._edit_draft(ctx, expense_id, category=category)

    async def set_cost_center(
        self, ctx: UserContext, expense_id: int, cost_center: str
    ) -> Optional[Expense]:
        """Atribui o centro de custo de um rascunho em revisão (botão inline)."""
        return await self._edit_draft(ctx, expense_id, cost_center=cost_center)

    async def _edit_draft(
        self,
        ctx: UserContext,
        expense_id: int,
        *,
        category: Optional[str] = None,
        cost_center: Optional[str] = None,
    ) -> Optional[Expense]:
        async with self._uow_factory() as uow:
            expense = await uow.expenses.get(expense_id)
            if not self._is_actionable_draft(ctx, expense):
                return None
            if category is not None:
                expense.category = category
            if cost_center is not None:
                expense.cost_center = cost_center
            saved = await uow.expenses.update(expense)
            await uow.commit()
        log.info("rascunho editado", expense_id=expense_id, category=category, cost_center=cost_center)
        return saved

    async def list_recent(self, ctx: UserContext, limit: int = 5) -> list[Expense]:
        async with self._uow_factory() as uow:
            return await uow.expenses.list_recent(ctx.org_id, ctx.user_id, limit)

    async def summary(self, ctx: UserContext, months: int = 1) -> float:
        # Aproxima o mês em 30 dias, mantendo o comportamento atual do /resumo.
        since = (datetime.now() - timedelta(days=30 * months)).date()
        async with self._uow_factory() as uow:
            return await uow.expenses.sum_since(ctx.org_id, ctx.user_id, since)

    @staticmethod
    def _is_actionable_draft(ctx: UserContext, expense: Optional[Expense]) -> bool:
        return (
            expense is not None
            and expense.org_id == ctx.org_id
            and expense.user_id == ctx.user_id
            and expense.status == ExpenseStatus.PENDING_REVIEW
        )

    @staticmethod
    def _parse_date(raw: str) -> date:
        try:
            return datetime.strptime(raw, "%d/%m/%Y").date()
        except (ValueError, TypeError):
            return date.today()
