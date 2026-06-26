"""Adapter de canal Telegram — implementa o port `MessagingChannel`.

Toda dependência de `python-telegram-bot` fica confinada aqui. O modo de
ingestão (long polling) é detalhe interno: o núcleo só recebe `IncomingMessage`
normalizado. Trocar para webhook não tocaria em `core/`, apenas neste arquivo.

Os handlers só traduzem update → `IncomingMessage` e delegam ao handler do
núcleo. Nenhuma regra de negócio mora aqui.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.core.entities import Channel
from src.core.ports.messaging import (
    ChannelResponder,
    IncomingMessage,
    InteractivePrompt,
    MediaItem,
    MessageHandler as CoreHandler,
    MessagingChannel,
)
from src.core.ports.notifications import Notifier
from src.logging_config import get_logger

log = get_logger(__name__)


class _TelegramResponder(ChannelResponder):
    """Responder ligado a um chat. Renderiza prompts abstratos como inline keyboard."""

    def __init__(self, bot, chat_id: int):
        self._bot = bot
        self._chat_id = chat_id

    async def send_text(self, text: str) -> None:
        await self._bot.send_message(chat_id=self._chat_id, text=text)

    async def send_prompt(self, prompt: InteractivePrompt) -> None:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(a.label, callback_data=a.key)] for a in prompt.actions]
        )
        await self._bot.send_message(
            chat_id=self._chat_id, text=prompt.text, reply_markup=keyboard
        )


class TelegramChannel(MessagingChannel, Notifier):
    def __init__(self, token: str):
        self._app = ApplicationBuilder().token(token).build()
        self._handler: CoreHandler | None = None

    @property
    def channel(self) -> Channel:
        return Channel.TELEGRAM

    # --- Notifier: push proativo (fora de uma conversa em curso) -------------

    async def notify(self, channel: Channel, external_id: str, text: str) -> bool:
        if channel is not Channel.TELEGRAM:
            return False
        try:
            # Em chat privado o external_id (user id) é o próprio chat id.
            await self._app.bot.send_message(chat_id=int(external_id), text=text)
            return True
        except Exception:
            # Usuário pode nunca ter iniciado conversa com o bot, ou tê-lo bloqueado.
            log.warning("falha ao notificar", external_id=external_id)
            return False

    def set_handler(self, handler: CoreHandler) -> None:
        self._handler = handler

    def run(self) -> None:
        if self._handler is None:
            raise RuntimeError("Handler não registrado (chame set_handler antes de run).")

        self._app.add_handler(MessageHandler(filters.PHOTO, self._on_photo))
        self._app.add_handler(
            MessageHandler(filters.TEXT | filters.COMMAND, self._on_text)
        )
        self._app.add_handler(CallbackQueryHandler(self._on_callback))

        log.info("Telegram channel iniciando (long polling)")
        self._app.run_polling()

    # --- Tradução update -> IncomingMessage ---------------------------------

    def _responder(self, update: Update) -> _TelegramResponder:
        return _TelegramResponder(self._app.bot, update.effective_chat.id)

    async def _dispatch(self, message: IncomingMessage, responder: ChannelResponder) -> None:
        try:
            await self._handler(message, responder)
        except Exception:
            log.exception("erro ao processar mensagem", external_user_id=message.external_user_id)
            await responder.send_text("⚠️ Ocorreu um erro ao processar sua mensagem.")

    async def _on_text(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        message = IncomingMessage(
            channel=Channel.TELEGRAM,
            external_user_id=str(update.effective_user.id),
            external_chat_id=str(update.effective_chat.id),
            sender_name=update.effective_user.first_name or "",
            text=update.message.text,
        )
        await self._dispatch(message, self._responder(update))

    async def _on_photo(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        # O download da mídia é responsabilidade do adapter; o núcleo recebe bytes.
        photo_file = await update.message.photo[-1].get_file()
        data = bytes(await photo_file.download_as_bytearray())
        message = IncomingMessage(
            channel=Channel.TELEGRAM,
            external_user_id=str(update.effective_user.id),
            external_chat_id=str(update.effective_chat.id),
            sender_name=update.effective_user.first_name or "",
            text=update.message.caption,
            media=[MediaItem(mime_type="image/jpeg", data=data)],
        )
        await self._dispatch(message, self._responder(update))

    async def _on_callback(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()  # encerra o "loading" no cliente
        message = IncomingMessage(
            channel=Channel.TELEGRAM,
            external_user_id=str(update.effective_user.id),
            external_chat_id=str(update.effective_chat.id),
            sender_name=update.effective_user.first_name or "",
            action=query.data,
        )
        await self._dispatch(message, self._responder(update))
