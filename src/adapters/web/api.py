"""Adapter de entrada (driving) HTTP — a API do painel web (FastAPI).

Mesma posição arquitetural que o `TelegramChannel`: traduz HTTP ⇄ chamadas de
serviço e **não contém regra de negócio**. Reusa `OrgService`/`AuthService`/
`ReportService`/`NotaService` — exatamente a mesma camada do bot. Pensada para uma
SPA (React/Vite) consumir: JSON, CORS e auth por Bearer token.

Auth: o usuário pede `/login` no bot, recebe um magic-link com um token de
troca; o front chama `/auth/exchange` e guarda o token de sessão, enviado como
`Authorization: Bearer <token>` nas demais chamadas. Relatórios são restritos a
admin/owner (o painel é a visão do gestor; o funcionário segue no canal).
"""
import csv
import io
from datetime import date, datetime
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from src.core.entities import NotaStatus
from src.core.services.auth_service import AuthService
from src.core.services.nota_service import NotaService, valor_a_pagar
from src.core.services.org_service import OrgService, UserContext
from src.core.services.report_service import ReportFilter, ReportOverview, ReportService


class ExchangeRequest(BaseModel):
    token: str


class TokenResponse(BaseModel):
    session_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    user_id: int
    org_id: int
    display_name: str
    is_admin: bool


class NotaSummaryOut(BaseModel):
    id: int
    numero: Optional[int]
    competencia: date
    status: str
    vencimento: Optional[date]
    author: str


class ItemOut(BaseModel):
    id: int
    date: date
    store_name: str
    category: str
    cost_center: Optional[str]
    total_amount: float


class NotaDetailOut(NotaSummaryOut):
    items: list[ItemOut]
    total: float
    outras_retencoes: float
    valor_a_pagar: float
    observacoes: Optional[str]
    decision_comment: Optional[str]


def create_api(
    *,
    auth_service: AuthService,
    org_service: OrgService,
    report_service: ReportService,
    nota_service: NotaService,
    cors_origins: list[str],
) -> FastAPI:
    app = FastAPI(title="Pedro Finanças — Painel", version="5.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    bearer = HTTPBearer(auto_error=True)

    async def current_context(
        creds: HTTPAuthorizationCredentials = Depends(bearer),
    ) -> UserContext:
        user_id = auth_service.verify_session(creds.credentials)
        if user_id is None:
            raise HTTPException(status_code=401, detail="Sessão inválida ou expirada.")
        ctx = await org_service.web_context(user_id)
        if ctx is None:
            raise HTTPException(status_code=401, detail="Usuário sem organização.")
        return ctx

    async def require_admin(ctx: UserContext = Depends(current_context)) -> UserContext:
        if not await org_service.is_admin(ctx):
            raise HTTPException(status_code=403, detail="Apenas admin/owner acessam o painel.")
        return ctx

    @app.get("/")
    async def health() -> dict:
        return {"status": "ok", "service": "pedro-financas-painel"}

    @app.post("/auth/exchange", response_model=TokenResponse)
    async def exchange(body: ExchangeRequest) -> TokenResponse:
        session = auth_service.exchange(body.token)
        if session is None:
            raise HTTPException(status_code=401, detail="Token de login inválido ou expirado.")
        return TokenResponse(session_token=session)

    @app.get("/auth/me", response_model=MeResponse)
    async def me(ctx: UserContext = Depends(current_context)) -> MeResponse:
        return MeResponse(
            user_id=ctx.user_id,
            org_id=ctx.org_id,
            display_name=ctx.display_name,
            is_admin=await org_service.is_admin(ctx),
        )

    @app.get("/reports/overview", response_model=ReportOverview)
    async def overview(
        ctx: UserContext = Depends(require_admin),
        date_from: Optional[date] = Query(None, alias="from"),
        date_to: Optional[date] = Query(None, alias="to"),
        status: Optional[str] = Query(None, description="status da nota (ex.: aprovada)"),
    ) -> ReportOverview:
        flt = ReportFilter(date_from=date_from, date_to=date_to, nota_status=_parse_nota_status(status))
        return await report_service.overview(ctx.org_id, flt)

    @app.get("/reports/export.csv")
    async def export_csv(
        ctx: UserContext = Depends(require_admin),
        date_from: Optional[date] = Query(None, alias="from"),
        date_to: Optional[date] = Query(None, alias="to"),
        status: Optional[str] = Query(None),
    ) -> Response:
        flt = ReportFilter(date_from=date_from, date_to=date_to, nota_status=_parse_nota_status(status))
        expenses = await report_service.list_for_export(ctx.org_id, flt)
        names: dict[int, str] = {}
        for e in expenses:
            if e.user_id not in names:
                names[e.user_id] = await org_service.user_name(e.user_id) or str(e.user_id)
        return _csv_response(expenses, names)

    @app.get("/notas", response_model=list[NotaSummaryOut])
    async def list_notas(ctx: UserContext = Depends(current_context)) -> list[NotaSummaryOut]:
        # Gestor vê as notas da empresa; funcionário, as suas.
        is_admin = await org_service.is_admin(ctx)
        notas = (
            await nota_service.list_for_org(ctx) if is_admin
            else await nota_service.list_for_user(ctx)
        )
        out = []
        for n in notas:
            out.append(
                NotaSummaryOut(
                    id=n.id,
                    numero=n.numero,
                    competencia=n.competencia,
                    status=n.status.value,
                    vencimento=n.vencimento,
                    author=await org_service.user_name(n.user_id) or str(n.user_id),
                )
            )
        return out

    @app.get("/notas/{nota_id}", response_model=NotaDetailOut)
    async def get_nota(nota_id: int, ctx: UserContext = Depends(current_context)) -> NotaDetailOut:
        is_admin = await org_service.is_admin(ctx)
        result = await nota_service.get_with_items(ctx, nota_id, include_others=is_admin)
        if result is None:
            raise HTTPException(status_code=404, detail="Nota não encontrada.")
        nota, items = result
        return NotaDetailOut(
            id=nota.id,
            numero=nota.numero,
            competencia=nota.competencia,
            status=nota.status.value,
            vencimento=nota.vencimento,
            author=await org_service.user_name(nota.user_id) or str(nota.user_id),
            items=[
                ItemOut(
                    id=e.id,
                    date=e.date,
                    store_name=e.store_name,
                    category=e.category,
                    cost_center=e.cost_center,
                    total_amount=e.total_amount,
                )
                for e in items
            ],
            total=round(sum(e.total_amount for e in items), 2),
            outras_retencoes=nota.outras_retencoes,
            valor_a_pagar=valor_a_pagar(nota, items),
            observacoes=nota.observacoes,
            decision_comment=nota.decision_comment,
        )

    return app


def _parse_nota_status(raw: Optional[str]) -> Optional[NotaStatus]:
    if not raw:
        return None
    try:
        return NotaStatus(raw.strip())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"status inválido: {raw}")


def _csv_response(expenses, names: dict) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["id", "data", "funcionario", "loja", "categoria", "centro_custo",
         "valor", "pagamento"]
    )
    for e in expenses:
        writer.writerow([
            e.id,
            e.date.strftime("%Y-%m-%d"),
            names.get(e.user_id, e.user_id),
            e.store_name,
            e.category,
            e.cost_center or "",
            f"{e.total_amount:.2f}",
            e.payment_method or "",
        ])
    stamp = datetime.now().strftime("%Y%m%d")
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="gastos-{stamp}.csv"'},
    )
