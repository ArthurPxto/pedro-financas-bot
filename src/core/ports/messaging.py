"""Port de canal de mensagens.

O núcleo fala com qualquer canal (Telegram, WhatsApp, ...) através destas
abstrações. Nada aqui assume primitivas específicas de um canal — nem inline
keyboard do Telegram, nem quick-reply do WhatsApp. Cada adapter renderiza os
prompts interativos à sua maneira.

Fluxo:
  1. O adapter recebe algo do canal (via polling OU webhook — escondido dele).
  2. Normaliza para `IncomingMessage`.
  3. Cria um `ChannelResponder` ligado àquela conversa.
  4. Chama o handler da aplicação: `await handle(message, responder)`.
  5. O handler usa o responder para responder texto ou emitir prompts.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from src.core.entities import Channel


@dataclass
class MediaItem:
    """Mídia já baixada pelo adapter. O núcleo recebe os bytes prontos."""

    mime_type: str
    data: bytes
    filename: Optional[str] = None


@dataclass
class IncomingMessage:
    """Mensagem normalizada, neutra de canal, entregue ao núcleo.

    `action` é preenchido quando a mensagem é a resposta a um prompt interativo
    (o usuário clicou em "confirmar"/"cancelar"/...). Nesse caso `action` carrega
    a `key` da `PromptAction` escolhida, independente de como o canal a renderizou.
    """

    channel: Channel
    external_user_id: str
    external_chat_id: str
    sender_name: str = ""
    text: Optional[str] = None
    media: list[MediaItem] = field(default_factory=list)
    action: Optional[str] = None


@dataclass(frozen=True)
class PromptAction:
    """Uma opção de um prompt interativo.

    `key` é o identificador neutro devolvido ao núcleo quando escolhido;
    `label` é o texto exibido. Cada adapter mapeia isso para sua primitiva.
    """

    key: str
    label: str


@dataclass
class InteractivePrompt:
    """Pedido de decisão ao usuário (ex.: confirmar / editar / cancelar).

    Abstrato de propósito: o adapter decide como apresentar as `actions`.
    """

    text: str
    actions: list[PromptAction]


class ChannelResponder(ABC):
    """Canal de resposta ligado a uma conversa específica.

    Entregue pelo adapter ao handler do núcleo. Permite responder sem que o
    núcleo conheça chat ids, tokens de callback ou qualquer detalhe do canal.
    """

    @abstractmethod
    async def send_text(self, text: str) -> None:
        ...

    @abstractmethod
    async def send_prompt(self, prompt: InteractivePrompt) -> None:
        ...


# Assinatura do handler da aplicação que o adapter invoca por mensagem recebida.
MessageHandler = Callable[[IncomingMessage, ChannelResponder], Awaitable[None]]


class MessagingChannel(ABC):
    """Port de um canal de mensagens.

    O adapter esconde o modo de ingestão (long polling, webhook, ...). Trocar
    ou somar um modo de entrada não deve tocar em `core/`: o núcleo só recebe
    `IncomingMessage` normalizado, venha de onde vier.
    """

    @property
    @abstractmethod
    def channel(self) -> Channel:
        ...

    @abstractmethod
    def set_handler(self, handler: MessageHandler) -> None:
        """Registra o handler do núcleo que processa cada mensagem recebida."""

    @abstractmethod
    def run(self) -> None:
        """Inicia a ingestão e bloqueia. O modo (polling/webhook) é interno ao adapter.

        Síncrono de propósito: o adapter gerencia seu próprio event loop (o
        long polling do Telegram, o servidor HTTP de um webhook, etc.). Os
        handlers do núcleo continuam sendo corrotinas, executadas dentro dele.
        """
