"""Composition root da API web (Fase 3).

Processo separado do bot (`src.main`), compartilhando o mesmo banco e a mesma
camada de serviço. Roda com: `.venv/bin/python -m src.api` (uvicorn embutido).
"""
import uvicorn

from src.adapters.persistence.database import create_engine, create_session_factory
from src.adapters.persistence.repositories import SqlAlchemyUnitOfWork
from src.adapters.security.jwt_issuer import JwtTokenIssuer
from src.adapters.web.api import create_api
from src.config import get_settings
from src.core.services.auth_service import AuthService
from src.core.services.org_service import OrgService
from src.core.services.report_service import ReportService
from src.logging_config import configure_logging, get_logger


def build_app():
    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)
    if not settings.web_jwt_secret:
        raise RuntimeError(
            "WEB_JWT_SECRET não definido — obrigatório para a API do painel."
        )

    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    uow_factory = lambda: SqlAlchemyUnitOfWork(session_factory)  # noqa: E731

    token_issuer = JwtTokenIssuer(secret=settings.web_jwt_secret)
    return create_api(
        auth_service=AuthService(token_issuer),
        org_service=OrgService(uow_factory),
        report_service=ReportService(uow_factory),
        cors_origins=settings.cors_origins_list,
    )


def main() -> None:
    settings = get_settings()
    log = get_logger("api")
    log.info("API do painel iniciando", host=settings.api_host, port=settings.api_port)
    uvicorn.run(build_app(), host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
