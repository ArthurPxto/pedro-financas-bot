"""Composition root.

Único lugar que instancia adapters concretos e os injeta nos serviços e no
roteador da aplicação. Não há lógica de negócio aqui, nem singletons criados
no import: tudo é montado dentro de `main()`, no boot.
"""
from src.adapters.ai_engine import GeminiExpenseExtractor
from src.adapters.messaging.telegram_adapter import TelegramChannel
from src.adapters.persistence.database import create_engine, create_session_factory
from src.adapters.persistence.repositories import SqlAlchemyUnitOfWork
from src.adapters.storage.filesystem import FilesystemReceiptStorage
from src.app import BotApplication
from src.config import get_settings
from src.core.services.expense_service import ExpenseService
from src.core.services.org_service import OrgService
from src.logging_config import configure_logging, get_logger


def main() -> None:
    settings = get_settings()  # valida o env no boot; falha cedo se faltar algo
    configure_logging(level=settings.log_level, json_output=settings.log_json)
    log = get_logger("main")

    # Adapters de saída (driven)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    uow_factory = lambda: SqlAlchemyUnitOfWork(session_factory)  # noqa: E731

    extractor = GeminiExpenseExtractor(
        api_key=settings.gemini_api_key, model_name=settings.gemini_model
    )
    receipts = FilesystemReceiptStorage(base_dir=settings.receipt_storage_dir)

    # Adapter de entrada (driving) — Telegram atrás do port de canal.
    # Criado antes dos serviços porque também é o Notifier (push proativo).
    channel = TelegramChannel(token=settings.telegram_token)

    # Serviços (núcleo)
    org_service = OrgService(uow_factory)
    expense_service = ExpenseService(uow_factory, extractor, receipts)
    app = BotApplication(org_service, expense_service, notifier=channel)

    channel.set_handler(app.handle)

    log.info("Bot iniciando", channel=channel.channel.value)
    channel.run()


if __name__ == "__main__":
    main()
