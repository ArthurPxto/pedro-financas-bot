"""Popula dados de exemplo e imprime um link de acesso ao painel.

Atalho para ver o dashboard rodando **sem precisar do bot do Telegram**: cria
uma empresa demo (gestora + 2 funcionários) com gastos variados (categorias,
centros de custo, pessoas, meses e status) e gera um magic-link já válido.

Rode da raiz do repo:

    .venv/bin/python -m scripts.seed_demo

Reexecutar é seguro: não duplica os dados; só imprime um link novo (o token
expira em 10 min). Precisa de WEB_JWT_SECRET no .env e do Postgres no ar.
"""
import asyncio
from datetime import date, datetime

from src.adapters.persistence.database import create_engine, create_session_factory
from src.adapters.persistence.repositories import SqlAlchemyUnitOfWork
from src.adapters.security.jwt_issuer import JwtTokenIssuer
from src.config import get_settings
from src.core.entities import Channel, Expense, ExpenseStatus
from src.core.services.auth_service import AuthService
from src.core.services.org_service import OrgService

COMPANY = "ACME Demo"
CATEGORIES = ["Alimentação", "Transporte", "Hospedagem", "Material de escritório"]
COST_CENTERS = ["Comercial", "Operações", "Diretoria"]

# (funcionário, loja, valor, categoria, centro, data, status)
A, B, G = "ana", "bruno", "admin"
DEMO = [
    (A, "Restaurante Sabor", 87.50, "Alimentação", "Comercial", date(2026, 2, 10), "approved"),
    (A, "Uber", 32.00, "Transporte", "Comercial", date(2026, 2, 12), "reimbursed"),
    (A, "Hotel Ibis", 320.00, "Hospedagem", "Comercial", date(2026, 3, 5), "approved"),
    (B, "Posto Shell", 210.00, "Transporte", "Operações", date(2026, 3, 20), "approved"),
    (B, "Kalunga", 145.90, "Material de escritório", "Operações", date(2026, 4, 2), "submitted"),
    (B, "Padaria do Zé", 24.00, "Alimentação", "Operações", date(2026, 4, 15), "rejected"),
    (A, "99 Táxi", 41.30, "Transporte", "Comercial", date(2026, 5, 8), "submitted"),
    (A, "Mercado Extra", 198.70, "Alimentação", "Operações", date(2026, 5, 22), "approved"),
    (G, "Notebook Dell", 4200.00, "Material de escritório", "Diretoria", date(2026, 5, 28), "reimbursed"),
    (B, "Correios", 126.09, "Transporte", "Operações", date(2026, 6, 3), "approved"),
    (A, "Hotel Mercure", 540.00, "Hospedagem", "Comercial", date(2026, 6, 10), "submitted"),
    (G, "Almoço cliente", 156.00, "Alimentação", "Diretoria", date(2026, 6, 18), "approved"),
]
_ALL_STATUSES = list(ExpenseStatus)


async def main() -> None:
    settings = get_settings()
    if not settings.web_jwt_secret:
        raise SystemExit("Defina WEB_JWT_SECRET no .env antes de rodar o seed.")

    engine = create_engine(settings.database_url)
    uow_factory = lambda: SqlAlchemyUnitOfWork(create_session_factory(engine))  # noqa: E731
    org = OrgService(uow_factory)

    # Gestora + empresa (idempotente: reusa se já existir)
    admin = await org.resolve_context(Channel.TELEGRAM, "demo-admin", "Gestora Demo")
    company = next((o for o, _ in await org.list_organizations(admin) if o.name == COMPANY), None)
    if company is None:
        company = await org.create_organization(admin, COMPANY)
    admin = await org.resolve_context(Channel.TELEGRAM, "demo-admin", "Gestora Demo")

    # Funcionários entram na empresa
    people = {G: admin}
    for ext, name in [(A, "Ana"), (B, "Bruno")]:
        ctx = await org.resolve_context(Channel.TELEGRAM, f"demo-{ext}", name)
        await org.join_organization(ctx, company.join_code)
        people[ext] = await org.resolve_context(Channel.TELEGRAM, f"demo-{ext}", name)

    for c in CATEGORIES:
        await org.add_category(admin, c)
    for cc in COST_CENTERS:
        await org.add_cost_center(admin, cc)

    # Gastos (só se ainda não houver nenhum na empresa)
    async with uow_factory() as uow:
        existing = await uow.expenses.list_filtered(company.id, statuses=_ALL_STATUSES)
        if existing:
            print(f"• Empresa '{COMPANY}' já tem {len(existing)} gastos — pulando o seed.")
        else:
            now = datetime.now()
            for ext, store, amount, cat, cc, when, status in DEMO:
                st = ExpenseStatus(status)
                decided = st in (ExpenseStatus.APPROVED, ExpenseStatus.REJECTED, ExpenseStatus.REIMBURSED)
                await uow.expenses.add(
                    Expense(
                        org_id=company.id,
                        user_id=people[ext].user_id,
                        store_name=store,
                        total_amount=amount,
                        category=cat,
                        date=when,
                        cost_center=cc,
                        status=st,
                        approver_id=admin.user_id if decided else None,
                        decision_comment="Sem comprovante" if st is ExpenseStatus.REJECTED else None,
                        decided_at=now if decided else None,
                    )
                )
            await uow.commit()
            print(f"• {len(DEMO)} gastos de exemplo criados em '{COMPANY}'.")

    # Magic-link de acesso (mesma mecânica do /login no bot)
    auth = AuthService(JwtTokenIssuer(secret=settings.web_jwt_secret))
    token = auth.create_login_token(admin.user_id)
    base = settings.web_base_url.rstrip("/")
    await engine.dispose()

    print("\n" + "=" * 64)
    print("Abra este link no navegador (expira em 10 min):\n")
    print(f"  {base}/login?token={token}")
    print("\nEmpresa:", COMPANY, "| código de convite:", company.join_code)
    print("Gestora: 'Gestora Demo' (admin) | Funcionários: Ana, Bruno")
    print("=" * 64)


if __name__ == "__main__":
    asyncio.run(main())
