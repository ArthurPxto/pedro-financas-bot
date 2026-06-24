"""Configuração de logging estruturado (structlog).

Substitui os `print()` espalhados pelo código. Chamado uma vez no boot,
pelo composition root.
"""
import logging
import sys

import structlog


def configure_logging(level: str = "INFO", json_output: bool = False) -> None:
    """Configura structlog + logging stdlib para a aplicação inteira.

    Args:
        level: nível mínimo (DEBUG, INFO, WARNING, ...).
        json_output: se True, renderiza logs como JSON (produção);
            caso contrário, console colorido e legível (desenvolvimento).
    """
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Atalho para obter um logger nomeado."""
    return structlog.get_logger(name)
