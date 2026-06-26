"""Popula dados de exemplo e imprime um link de acesso ao painel.

Atalho para ver o dashboard rodando **sem precisar do bot do Telegram**: cria
uma empresa demo (gestora + 2 funcionários) com notas de débito em vários
estados (aberta, aguardando, aprovada, rejeitada, paga) e seus itens, e gera um
magic-link já válido.

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
from src.core.entities import Channel, Expense, ExpenseStatus, NotaDebito, NotaStatus
from src.core.services.auth_service import AuthService
from src.core.services.nota_service import fifth_business_day_next_month, first_of_month
from src.core.services.org_service import OrgService

COMPANY = "ACME Demo"
CATEGORIES = ["Alimentação", "Transporte", "Hospedagem", "Material de escritório"]
COST_CENTERS = ["Comercial", "Operações", "Diretoria"]

# Cada nota: (autor, competência, status, [(loja, valor, categoria, centro), ...], motivo)
A, B, G = "ana", "bruno", "admin"
NOTAS = [
    (A, date(2026, 2, 1), "paga", [
        ("Mercado Extra", 100.0, "Alimentação", "Comercial"),
        ("Uber", 32.0, "Transporte", "Comercial"),
    ], None),
    (B, date(2026, 3, 1), "aprovada", [
        ("Posto Shell", 210.0, "Transporte", "Operações"),
        ("Hotel Ibis", 320.0, "Hospedagem", "Operações"),
    ], None),
    (G, date(2026, 5, 1), "aprovada", [
        ("Notebook Dell", 4200.0, "Material de escritório", "Diretoria"),
    ], None),
    (A, date(2026, 4, 1), "fechada", [
        ("Kalunga", 145.90, "Material de escritório", "Comercial"),
        ("99 Táxi", 41.30, "Transporte", "Comercial"),
    ], None),
    (B, date(2026, 4, 1), "rejeitada", [
        ("Padaria do Zé", 24.0, "Alimentação", "Operações"),
    ], "Sem comprovante"),
    (A, date(2026, 6, 1), "aberta", [
        ("Correios", 126.09, "Transporte", "Comercial"),
        ("Hotel Mercure", 540.0, "Hospedagem", "Comercial"),
    ], None),
]


async def main() -> None:
    settings = get_settings()
    if not settings.web_jwt_secret:
        raise SystemExit("Defina WEB_JWT_SECRET no .env antes de rodar o seed.")

    engine = create_engine(settings.database_url)
    uow_factory = lambda: SqlAlchemyUnitOfWork(create_session_factory(engine))  # noqa: E731
    org = OrgService(uow_factory)

    admin = await org.resolve_context(Channel.TELEGRAM, "demo-admin", "Gestora Demo")
    company = next((o for o, _ in await org.list_organizations(admin) if o.name == COMPANY), None)
    if company is None:
        company = await org.create_organization(admin, COMPANY)
    admin = await org.resolve_context(Channel.TELEGRAM, "demo-admin", "Gestora Demo")
    await org.set_org_fiscal(admin, cnpj="55.196.121/0001-42", address="Rua Pais Leme, 215 - São Paulo", cep="05424150")

    people = {G: admin}
    for ext, name in [(A, "Ana"), (B, "Bruno")]:
        ctx = await org.resolve_context(Channel.TELEGRAM, f"demo-{ext}", name)
        await org.join_organization(ctx, company.join_code)
        people[ext] = await org.resolve_context(Channel.TELEGRAM, f"demo-{ext}", name)

    for c in CATEGORIES:
        await org.add_category(admin, c)
    for cc in COST_CENTERS:
        await org.add_cost_center(admin, cc)

    async with uow_factory() as uow:
        existing = await uow.notas.list_for_org(company.id)
        if existing:
            print(f"• Empresa '{COMPANY}' já tem {len(existing)} notas — pulando o seed.")
        else:
            now = datetime.now()
            numero = 0
            for ext, comp, status_str, items, motivo in NOTAS:
                st = NotaStatus(status_str)
                closed = st != NotaStatus.ABERTA
                if closed:
                    numero += 1
                nota = await uow.notas.add(
                    NotaDebito(
                        org_id=company.id,
                        user_id=people[ext].user_id,
                        numero=numero if closed else None,
                        competencia=first_of_month(comp),
                        status=st,
                        vencimento=fifth_business_day_next_month(comp) if closed else None,
                    )
                )
                if st in (NotaStatus.APROVADA, NotaStatus.REJEITADA, NotaStatus.PAGA):
                    nota.approver_id = admin.user_id
                    nota.decided_at = now
                    nota.decision_comment = motivo
                    await uow.notas.update(nota)
                for store, amount, cat, cc in items:
                    await uow.expenses.add(
                        Expense(
                            org_id=company.id,
                            user_id=people[ext].user_id,
                            store_name=store,
                            total_amount=amount,
                            category=cat,
                            date=comp,
                            cost_center=cc,
                            status=ExpenseStatus.CONFIRMED,
                            nota_id=nota.id,
                        )
                    )
            await uow.commit()
            print(f"• {len(NOTAS)} notas de exemplo criadas em '{COMPANY}'.")

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
