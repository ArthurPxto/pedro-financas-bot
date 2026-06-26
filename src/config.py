"""Configuração central da aplicação.

Toda variável de ambiente é lida e validada aqui, uma única vez, no boot.
Nenhum outro módulo deve chamar `os.getenv` diretamente.
"""
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração tipada e validada da aplicação.

    Falha no boot (ValidationError) se algo obrigatório estiver ausente,
    em vez de explodir tarde, no meio de um fluxo.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Canais ---
    telegram_token: str = Field(description="Token do bot obtido no @BotFather")

    # --- IA ---
    gemini_api_key: str = Field(description="Chave do Google AI Studio")
    gemini_model: str = Field(default="gemini-2.5-flash")

    # --- Banco ---
    # Ex.: postgresql+asyncpg://pedro:pedro@localhost:5432/pedro_financas
    database_url: str = Field(
        default="postgresql+asyncpg://pedro:pedro@localhost:5432/pedro_financas",
        description="DSN async do PostgreSQL (driver asyncpg)",
    )

    # --- Armazenamento de comprovantes ---
    # Backend de storage. Hoje só "filesystem"; "s3" fica para depois.
    receipt_storage_backend: str = Field(default="filesystem")
    receipt_storage_dir: Path = Field(
        default=Path("data/receipts"),
        description="Diretório raiz para comprovantes quando backend=filesystem",
    )

    # --- Painel web / API (Fase 3) ---
    # Segredo para assinar os tokens JWT do painel. Opcional: o bot sobe sem ele,
    # mas `/login` e a API exigem que esteja definido.
    web_jwt_secret: Optional[str] = Field(
        default=None, description="Segredo HMAC dos JWT do painel web"
    )
    web_base_url: str = Field(
        default="http://localhost:5173",
        description="URL do frontend (SPA) — base do magic-link enviado pelo canal",
    )
    web_cors_origins: str = Field(
        default="*",
        description="Origens permitidas no CORS da API, separadas por vírgula",
    )
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)

    # --- Observabilidade ---
    log_level: str = Field(default="INFO")
    log_json: bool = Field(
        default=False,
        description="Se True, emite logs em JSON (produção). Caso contrário, console legível.",
    )

    @property
    def alembic_database_url(self) -> str:
        """DSN síncrono para o Alembic (usa psycopg/psycopg2 em vez de asyncpg)."""
        return self.database_url.replace("+asyncpg", "")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.web_cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retorna a instância única de configuração, criada na primeira chamada.

    Não é instanciada no import do módulo: importar `config` nunca falha
    por env ausente — só falha quem realmente pede a configuração no boot.
    """
    return Settings()  # type: ignore[call-arg]
