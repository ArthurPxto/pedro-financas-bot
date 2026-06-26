"""Roteador de aplicação — cola neutra de canal entre o port de mensagens e os serviços.

Implementa a assinatura `MessageHandler`: recebe `IncomingMessage` + `ChannelResponder`
e orquestra `OrgService`/`ExpenseService`. Não conhece Telegram nem WhatsApp — só fala
em termos de mensagens normalizadas e prompts interativos abstratos. É este o ponto que
a futura API web também poderá reaproveitar (ou chamar os serviços diretamente).
"""
from src.core.entities import Expense
from src.core.ports.messaging import (
    ChannelResponder,
    IncomingMessage,
    InteractivePrompt,
    PromptAction,
)
from src.core.services.expense_service import ExpenseService
from src.core.services.org_service import OrgService, UserContext
from src.logging_config import get_logger

log = get_logger(__name__)

# Chaves de ação neutras devolvidas pelos prompts (cabem nos 64 bytes do Telegram).
_CONFIRM = "exp_ok:"
_CANCEL = "exp_no:"


class BotApplication:
    def __init__(self, org_service: OrgService, expense_service: ExpenseService):
        self._org = org_service
        self._expenses = expense_service

    async def handle(self, message: IncomingMessage, responder: ChannelResponder) -> None:
        ctx = await self._org.resolve_context(
            message.channel, message.external_user_id, message.sender_name
        )

        if message.action:
            await self._handle_action(ctx, message.action, responder)
        elif message.media:
            await self._handle_photo(ctx, message, responder)
        elif message.text:
            await self._handle_text(ctx, message.text, responder)

    # --- Fluxos --------------------------------------------------------------

    async def _handle_photo(
        self, ctx: UserContext, message: IncomingMessage, responder: ChannelResponder
    ) -> None:
        await responder.send_text("Recebi a foto! Processando os dados com IA... 🤖")
        media = message.media[0]
        try:
            draft = await self._expenses.create_draft_from_image(ctx, media.data, media.mime_type)
        except Exception:
            log.exception("falha ao extrair gasto da imagem", user_id=ctx.user_id)
            await responder.send_text("⚠️ Não consegui ler o comprovante. Tente outra foto.")
            return

        await responder.send_prompt(
            InteractivePrompt(
                text=self._format_draft(draft),
                actions=[
                    PromptAction(f"{_CONFIRM}{draft.id}", "✅ Confirmar"),
                    PromptAction(f"{_CANCEL}{draft.id}", "❌ Cancelar"),
                ],
            )
        )

    async def _handle_action(
        self, ctx: UserContext, action: str, responder: ChannelResponder
    ) -> None:
        if action.startswith(_CONFIRM):
            expense_id = self._parse_id(action, _CONFIRM)
            saved = await self._expenses.confirm(ctx, expense_id) if expense_id else None
            if saved:
                await responder.send_text(f"✅ Gasto registrado!\n{self._format_expense(saved)}")
            else:
                await responder.send_text("Não encontrei esse rascunho para confirmar.")
        elif action.startswith(_CANCEL):
            expense_id = self._parse_id(action, _CANCEL)
            ok = await self._expenses.cancel(ctx, expense_id) if expense_id else False
            await responder.send_text("🗑️ Gasto descartado." if ok else "Nada a descartar.")

    async def _handle_text(
        self, ctx: UserContext, text: str, responder: ChannelResponder
    ) -> None:
        command, _, rest = text.strip().partition(" ")
        command = command.lower().lstrip("/")

        if command == "start":
            await responder.send_text(self._start_message(ctx.display_name))
        elif command == "resumo":
            await self._reply_summary(ctx, rest.strip(), responder)
        elif command == "listar":
            await self._reply_recent(ctx, responder)
        else:
            await responder.send_text(
                "Envie a foto de um comprovante, ou use /resumo, /listar ou /start."
            )

    async def _reply_summary(
        self, ctx: UserContext, arg: str, responder: ChannelResponder
    ) -> None:
        months = 1
        if arg:
            try:
                months = int(arg)
            except ValueError:
                await responder.send_text("Use um número para os meses. Ex: /resumo 3")
                return
        total = await self._expenses.summary(ctx, months)
        await responder.send_text(
            f"📊 Resumo Financeiro\n"
            f"Período: Último(s) {months} mês(es)\n"
            f"💰 Total acumulado: R$ {total:.2f}"
        )

    async def _reply_recent(self, ctx: UserContext, responder: ChannelResponder) -> None:
        expenses = await self._expenses.list_recent(ctx)
        if not expenses:
            await responder.send_text("Nenhum gasto encontrado.")
            return
        lines = ["📋 Últimos gastos registrados:\n"]
        for e in expenses:
            lines.append(f"📅 {e.date.strftime('%d/%m/%Y')} - {e.store_name}: R$ {e.total_amount:.2f}")
        await responder.send_text("\n".join(lines))

    # --- Formatação ----------------------------------------------------------

    @staticmethod
    def _format_expense(e: Expense) -> str:
        return (
            f"📍 {e.store_name}\n"
            f"💰 R$ {e.total_amount:.2f}\n"
            f"📂 {e.category}\n"
            f"📅 Data: {e.date.strftime('%d/%m/%Y')}"
        )

    def _format_draft(self, e: Expense) -> str:
        return "Confira o gasto extraído:\n\n" + self._format_expense(e) + "\n\nConfirmar?"

    @staticmethod
    def _parse_id(action: str, prefix: str) -> int | None:
        try:
            return int(action[len(prefix):])
        except ValueError:
            return None

    @staticmethod
    def _start_message(name: str) -> str:
        return (
            f"Olá, {name}! 👋 Bem-vindo ao seu Assistente Financeiro.\n\n"
            "📸 Envie a foto de um comprovante e eu extraio valor, loja, data e categoria — "
            "você confirma antes de salvar.\n\n"
            "🚀 Comandos:\n"
            "/listar - últimos gastos\n"
            "/resumo - total do último mês\n"
            "/resumo 3 - total dos últimos 3 meses\n"
            "/start - esta mensagem"
        )
