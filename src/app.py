"""Roteador de aplicação — cola neutra de canal entre o port de mensagens e os serviços.

Implementa a assinatura `MessageHandler`: recebe `IncomingMessage` + `ChannelResponder`
e orquestra `OrgService`/`ExpenseService`. Não conhece Telegram nem WhatsApp — só fala
em termos de mensagens normalizadas e prompts interativos abstratos.
"""
from src.core.entities import Expense, ExpenseStatus, Role
from src.core.ports.messaging import (
    ChannelResponder,
    IncomingMessage,
    InteractivePrompt,
    PromptAction,
)
from typing import Optional

from src.core.ports.notifications import Notifier
from src.core.services.auth_service import AuthService
from src.core.services.expense_service import ExpenseService
from src.core.services.org_service import OrgService, UserContext
from src.logging_config import get_logger

log = get_logger(__name__)

# Chaves de ação neutras devolvidas pelos prompts (cabem nos 64 bytes do Telegram).
# Formato: "<verbo>:<expense_id>[:<índice>]".
_CONFIRM = "exp_ok"
_DELETE = "exp_no"
_OPEN_CAT = "exp_cat"   # abre o seletor de categoria
_OPEN_CC = "exp_cc"     # abre o seletor de centro de custo
_SET_CAT = "setcat"     # setcat:<id>:<idx>
_SET_CC = "setcc"       # setcc:<id>:<idx>
_APV_OK = "apv_ok"      # aprova um gasto:        apv_ok:<id>
_APV_NO = "apv_no"      # inicia rejeição:        apv_no:<id>
_APV_ALL = "apv_all"    # aprova todos pendentes
_APV_REIMB = "apv_reimb"  # marca reembolsado:    apv_reimb:<id>

# Rótulos amigáveis (PT) de cada estado, para a visão "meus reembolsos".
_STATUS_LABELS = {
    ExpenseStatus.PENDING_REVIEW: "📝 rascunho",
    ExpenseStatus.SUBMITTED: "⏳ aguardando aprovação",
    ExpenseStatus.APPROVED: "✅ aprovado",
    ExpenseStatus.REJECTED: "❌ rejeitado",
    ExpenseStatus.REIMBURSED: "💸 reembolsado",
}


class BotApplication:
    def __init__(
        self,
        org_service: OrgService,
        expense_service: ExpenseService,
        notifier: Notifier,
        auth_service: Optional[AuthService] = None,
        web_base_url: str = "",
    ):
        self._org = org_service
        self._expenses = expense_service
        self._notifier = notifier
        self._auth = auth_service
        self._web_base_url = web_base_url.rstrip("/")

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

    # --- Comandos de texto ---------------------------------------------------

    async def _handle_text(
        self, ctx: UserContext, text: str, responder: ChannelResponder
    ) -> None:
        command, _, rest = text.strip().partition(" ")
        command = command.lower().lstrip("/").split("@")[0]
        rest = rest.strip()

        handlers = {
            "start": lambda: responder.send_text(self._start_message(ctx.display_name)),
            "resumo": lambda: self._reply_summary(ctx, rest, responder),
            "listar": lambda: self._reply_recent(ctx, responder),
            "criar_empresa": lambda: self._create_org(ctx, rest, responder),
            "entrar": lambda: self._join_org(ctx, rest, responder),
            "empresa": lambda: self._show_org(ctx, responder),
            "empresas": lambda: self._list_orgs(ctx, responder),
            "trocar": lambda: self._switch_org(ctx, rest, responder),
            "gasto": lambda: self._manual_expense(ctx, rest, responder),
            "categorias": lambda: self._list_categories(ctx, responder),
            "add_categoria": lambda: self._add_category(ctx, rest, responder),
            "centros": lambda: self._list_cost_centers(ctx, responder),
            "add_centro": lambda: self._add_cost_center(ctx, rest, responder),
            "aprovacoes": lambda: self._list_approvals(ctx, responder),
            "aprovar": lambda: self._approve_command(ctx, rest, responder),
            "aprovar_todos": lambda: self._approve_all(ctx, responder),
            "rejeitar": lambda: self._reject_command(ctx, rest, responder),
            "reembolsar": lambda: self._reimburse_command(ctx, rest, responder),
            "reembolsos": lambda: self._my_reimbursements(ctx, responder),
            "login": lambda: self._web_login(ctx, responder),
        }
        handler = handlers.get(command)
        if handler:
            await handler()
        else:
            await responder.send_text(
                "Envie a foto de um comprovante, ou use /gasto, /resumo, /listar, "
                "/empresa ou /start."
            )

    # --- Onboarding ----------------------------------------------------------

    async def _create_org(self, ctx, name, responder) -> None:
        if not name:
            await responder.send_text("Use: /criar_empresa <nome da empresa>")
            return
        org = await self._org.create_organization(ctx, name)
        await responder.send_text(
            f"🏢 Empresa *{org.name}* criada! Você é admin.\n"
            f"Código de convite: `{org.join_code}`\n"
            f"Compartilhe com a equipe: cada pessoa envia `/entrar {org.join_code}`.\n\n"
            f"Seus gastos agora vão para esta empresa."
        )

    async def _join_org(self, ctx, code, responder) -> None:
        if not code:
            await responder.send_text("Use: /entrar <código>")
            return
        org = await self._org.join_organization(ctx, code)
        if org is None:
            await responder.send_text("Código inválido. Confira com o admin da empresa.")
            return
        await responder.send_text(
            f"✅ Você entrou em *{org.name}*. Seus gastos agora vão para esta empresa."
        )

    async def _show_org(self, ctx, responder) -> None:
        orgs = await self._org.list_organizations(ctx)
        active = next((o for o, _ in orgs if o.id == ctx.org_id), None)
        role = next((r for o, r in orgs if o.id == ctx.org_id), None)
        if active is None:
            await responder.send_text("Nenhuma empresa ativa.")
            return
        lines = [f"🏢 Empresa ativa: *{active.name}* ({role.value if role else '—'})"]
        if role in (Role.OWNER, Role.ADMIN) and active.join_code:
            lines.append(f"Código de convite: `{active.join_code}`")
        await responder.send_text("\n".join(lines))

    async def _list_orgs(self, ctx, responder) -> None:
        orgs = await self._org.list_organizations(ctx)
        lines = ["🏢 Suas empresas (use /trocar <id>):\n"]
        for org, role in orgs:
            marker = "👉 " if org.id == ctx.org_id else "   "
            lines.append(f"{marker}[{org.id}] {org.name} ({role.value})")
        await responder.send_text("\n".join(lines))

    async def _switch_org(self, ctx, arg, responder) -> None:
        try:
            org_id = int(arg)
        except ValueError:
            await responder.send_text("Use: /trocar <id> (veja /empresas)")
            return
        if await self._org.switch_active(ctx, org_id):
            await responder.send_text("✅ Empresa ativa alterada.")
        else:
            await responder.send_text("Você não é membro dessa empresa.")

    # --- Categorias / centros de custo --------------------------------------

    async def _list_categories(self, ctx, responder) -> None:
        cats = await self._org.list_categories(ctx)
        if cats:
            await responder.send_text("📂 Categorias da empresa:\n" + "\n".join(f"• {c}" for c in cats))
        else:
            await responder.send_text("Nenhuma categoria definida. Admin: /add_categoria <nome>")

    async def _add_category(self, ctx, name, responder) -> None:
        if not name:
            await responder.send_text("Use: /add_categoria <nome>")
            return
        result = await self._org.add_category(ctx, name)
        await responder.send_text(
            f"📂 Categoria '{result.name}' adicionada." if result
            else "Apenas admins podem gerenciar categorias."
        )

    async def _list_cost_centers(self, ctx, responder) -> None:
        ccs = await self._org.list_cost_centers(ctx)
        if ccs:
            await responder.send_text("🏢 Centros de custo:\n" + "\n".join(f"• {c}" for c in ccs))
        else:
            await responder.send_text("Nenhum centro de custo. Admin: /add_centro <nome>")

    async def _add_cost_center(self, ctx, name, responder) -> None:
        if not name:
            await responder.send_text("Use: /add_centro <nome>")
            return
        result = await self._org.add_cost_center(ctx, name)
        await responder.send_text(
            f"🏢 Centro de custo '{result.name}' adicionado." if result
            else "Apenas admins podem gerenciar centros de custo."
        )

    # --- Gastos --------------------------------------------------------------

    async def _manual_expense(self, ctx, rest, responder) -> None:
        amount_str, _, description = rest.partition(" ")
        try:
            amount = float(amount_str.replace(",", "."))
        except ValueError:
            await responder.send_text("Use: /gasto <valor> <descrição>. Ex: /gasto 50 mercado almoço")
            return
        draft = await self._expenses.create_manual_draft(ctx, amount, description)
        await self._send_draft_prompt(ctx, draft, responder)

    async def _handle_photo(self, ctx, message, responder) -> None:
        await responder.send_text("Recebi a foto! Processando os dados com IA... 🤖")
        media = message.media[0]
        try:
            draft = await self._expenses.create_draft_from_image(ctx, media.data, media.mime_type)
        except Exception:
            log.exception("falha ao extrair gasto da imagem", user_id=ctx.user_id)
            await responder.send_text("⚠️ Não consegui ler o comprovante. Tente outra foto.")
            return
        await self._send_draft_prompt(ctx, draft, responder)

    async def _send_draft_prompt(self, ctx, draft: Expense, responder) -> None:
        await responder.send_prompt(
            InteractivePrompt(
                text=self._format_draft(draft),
                actions=[
                    PromptAction(f"{_CONFIRM}:{draft.id}", "✅ Confirmar"),
                    PromptAction(f"{_OPEN_CAT}:{draft.id}", "📂 Categoria"),
                    PromptAction(f"{_OPEN_CC}:{draft.id}", "🏢 Centro de custo"),
                    PromptAction(f"{_DELETE}:{draft.id}", "❌ Excluir"),
                ],
            )
        )

    # --- Ações de prompt (callbacks) ----------------------------------------

    async def _handle_action(self, ctx: UserContext, action: str, responder) -> None:
        verb, _, args = action.partition(":")

        if verb == _CONFIRM:
            await self._confirm_draft(ctx, _to_int(args), responder)
        elif verb == _DELETE:
            ok = await self._expenses.cancel(ctx, _to_int(args))
            await responder.send_text("🗑️ Gasto excluído." if ok else "Nada a excluir.")
        elif verb == _OPEN_CAT:
            await self._open_picker(ctx, _to_int(args), responder, kind="cat")
        elif verb == _OPEN_CC:
            await self._open_picker(ctx, _to_int(args), responder, kind="cc")
        elif verb in (_SET_CAT, _SET_CC):
            await self._apply_picker(ctx, verb, args, responder)
        elif verb == _APV_OK:
            await self._approve_one(ctx, _to_int(args), responder)
        elif verb == _APV_NO:
            await self._prompt_reject(ctx, _to_int(args), responder)
        elif verb == _APV_ALL:
            await self._approve_all(ctx, responder)
        elif verb == _APV_REIMB:
            await self._reimburse(ctx, _to_int(args), responder)

    # --- Confirmação do rascunho (entra no fluxo de reembolso) ---------------

    async def _confirm_draft(self, ctx, expense_id, responder) -> None:
        # Quem já é aprovador (uso pessoal / admin) não precisa de fila: aprova direto.
        approve_directly = await self._org.is_admin(ctx)
        saved = await self._expenses.confirm(
            ctx, expense_id, approve_directly=approve_directly
        )
        if saved is None:
            await responder.send_text("Não encontrei esse rascunho para confirmar.")
        elif saved.status == ExpenseStatus.APPROVED:
            await responder.send_text(f"✅ Gasto registrado!\n{self._format_expense(saved)}")
        else:  # SUBMITTED — aguardando um aprovador
            await responder.send_text(
                f"📤 Gasto enviado para aprovação!\n{self._format_expense(saved)}\n\n"
                "Acompanhe o status em /reembolsos."
            )
            await self._notify_approvers(ctx)

    async def _open_picker(self, ctx, expense_id, responder, *, kind: str) -> None:
        if expense_id is None or await self._expenses.get_draft(ctx, expense_id) is None:
            await responder.send_text("Esse rascunho não está mais disponível para edição.")
            return
        options = (
            await self._org.list_categories(ctx) if kind == "cat"
            else await self._org.list_cost_centers(ctx)
        )
        if not options:
            label = "categoria" if kind == "cat" else "centro de custo"
            await responder.send_text(f"Nenhum(a) {label} definido(a). Admin pode adicionar.")
            return
        prefix = _SET_CAT if kind == "cat" else _SET_CC
        title = "Escolha a categoria:" if kind == "cat" else "Escolha o centro de custo:"
        await responder.send_prompt(
            InteractivePrompt(
                text=title,
                actions=[
                    PromptAction(f"{prefix}:{expense_id}:{idx}", name)
                    for idx, name in enumerate(options)
                ],
            )
        )

    async def _apply_picker(self, ctx, verb, args, responder) -> None:
        id_str, _, idx_str = args.partition(":")
        expense_id, idx = _to_int(id_str), _to_int(idx_str)
        if expense_id is None or idx is None:
            return
        is_cat = verb == _SET_CAT
        options = (
            await self._org.list_categories(ctx) if is_cat
            else await self._org.list_cost_centers(ctx)
        )
        if idx >= len(options):
            await responder.send_text("Opção indisponível, tente novamente.")
            return
        value = options[idx]
        updated = (
            await self._expenses.set_category(ctx, expense_id, value) if is_cat
            else await self._expenses.set_cost_center(ctx, expense_id, value)
        )
        if updated is None:
            await responder.send_text("Esse rascunho não está mais disponível para edição.")
            return
        # Reapresenta o rascunho atualizado para o usuário continuar ou confirmar.
        await self._send_draft_prompt(ctx, updated, responder)

    # --- Aprovação / reembolso ----------------------------------------------

    async def _list_approvals(self, ctx, responder) -> None:
        if not await self._require_approver(ctx, responder):
            return
        pending = await self._expenses.list_pending_approvals(ctx)
        if not pending:
            await responder.send_text("✅ Nenhum gasto aguardando aprovação.")
            return
        await responder.send_text(f"📋 {len(pending)} gasto(s) aguardando aprovação:")
        for e in pending:
            await responder.send_prompt(
                InteractivePrompt(
                    text=await self._format_approval_item(e),
                    actions=[
                        PromptAction(f"{_APV_OK}:{e.id}", "✅ Aprovar"),
                        PromptAction(f"{_APV_NO}:{e.id}", "❌ Rejeitar"),
                    ],
                )
            )
        if len(pending) > 1:
            await responder.send_prompt(
                InteractivePrompt(
                    text="Ou aprove todos de uma vez:",
                    actions=[PromptAction(_APV_ALL, f"✅ Aprovar todos ({len(pending)})")],
                )
            )

    async def _approve_command(self, ctx, rest, responder) -> None:
        expense_id = _to_int(rest)
        if expense_id is None:
            await responder.send_text("Use: /aprovar <id> (veja /aprovacoes)")
            return
        await self._approve_one(ctx, expense_id, responder)

    async def _approve_one(self, ctx, expense_id, responder) -> None:
        if not await self._require_approver(ctx, responder):
            return
        saved = await self._expenses.approve(ctx, expense_id)
        if saved is None:
            await responder.send_text("Esse gasto não está mais aguardando aprovação.")
            return
        await responder.send_text(f"✅ Gasto #{saved.id} aprovado.\n{self._format_expense(saved)}")
        await self._notify_author(
            ctx, saved, f"✅ Seu gasto em {saved.store_name} (R$ {saved.total_amount:.2f}) foi aprovado."
        )

    async def _approve_all(self, ctx, responder) -> None:
        if not await self._require_approver(ctx, responder):
            return
        approved = await self._expenses.approve_all(ctx)
        if not approved:
            await responder.send_text("Nenhum gasto aguardando aprovação.")
            return
        await responder.send_text(f"✅ {len(approved)} gasto(s) aprovado(s).")
        for e in approved:
            await self._notify_author(
                ctx, e, f"✅ Seu gasto em {e.store_name} (R$ {e.total_amount:.2f}) foi aprovado."
            )

    async def _prompt_reject(self, ctx, expense_id, responder) -> None:
        # A rejeição exige motivo; como o fluxo é stateless, pedimos via comando.
        if not await self._require_approver(ctx, responder):
            return
        if expense_id is None:
            return
        await responder.send_text(
            f"Para rejeitar o gasto #{expense_id}, envie o motivo:\n"
            f"/rejeitar {expense_id} <motivo>"
        )

    async def _reject_command(self, ctx, rest, responder) -> None:
        if not await self._require_approver(ctx, responder):
            return
        id_str, _, comment = rest.partition(" ")
        expense_id = _to_int(id_str)
        comment = comment.strip()
        if expense_id is None or not comment:
            await responder.send_text("Use: /rejeitar <id> <motivo>. O motivo é obrigatório.")
            return
        saved = await self._expenses.reject(ctx, expense_id, comment)
        if saved is None:
            await responder.send_text("Esse gasto não está mais aguardando aprovação.")
            return
        await responder.send_text(f"❌ Gasto #{saved.id} rejeitado.\nMotivo: {comment}")
        await self._notify_author(
            ctx,
            saved,
            f"❌ Seu gasto em {saved.store_name} (R$ {saved.total_amount:.2f}) foi rejeitado.\n"
            f"Motivo: {comment}",
        )

    async def _reimburse_command(self, ctx, rest, responder) -> None:
        expense_id = _to_int(rest)
        if expense_id is None:
            await responder.send_text("Use: /reembolsar <id>")
            return
        await self._reimburse(ctx, expense_id, responder)

    async def _reimburse(self, ctx, expense_id, responder) -> None:
        if not await self._require_approver(ctx, responder):
            return
        saved = await self._expenses.mark_reimbursed(ctx, expense_id)
        if saved is None:
            await responder.send_text("Só dá para reembolsar um gasto já aprovado.")
            return
        await responder.send_text(f"💸 Gasto #{saved.id} marcado como reembolsado.")
        await self._notify_author(
            ctx, saved, f"💸 Seu gasto em {saved.store_name} (R$ {saved.total_amount:.2f}) foi reembolsado."
        )

    async def _my_reimbursements(self, ctx, responder) -> None:
        items = await self._expenses.list_my_reimbursements(ctx)
        if not items:
            await responder.send_text("Você ainda não enviou gastos para reembolso.")
            return
        lines = ["🧾 Seus reembolsos:\n"]
        for e in items:
            label = _STATUS_LABELS.get(e.status, e.status.value)
            lines.append(f"#{e.id} {label} — {e.store_name}: R$ {e.total_amount:.2f}")
            if e.status == ExpenseStatus.REJECTED and e.decision_comment:
                lines.append(f"    ↳ motivo: {e.decision_comment}")
        await responder.send_text("\n".join(lines))

    # --- Acesso ao painel web ------------------------------------------------

    async def _web_login(self, ctx, responder) -> None:
        if self._auth is None or not self._web_base_url:
            await responder.send_text("O painel web ainda não está configurado.")
            return
        token = self._auth.create_login_token(ctx.user_id)
        await responder.send_text(
            "🔐 Seu acesso ao painel (expira em 10 min):\n"
            f"{self._web_base_url}/login?token={token}\n\n"
            "Abra no navegador. Não compartilhe — é a sua chave de acesso."
        )

    async def _require_approver(self, ctx, responder) -> bool:
        if await self._org.is_admin(ctx):
            return True
        await responder.send_text("Apenas aprovadores (admin/owner) da empresa podem fazer isso.")
        return False

    # --- Notificações push ---------------------------------------------------

    async def _notify_approvers(self, ctx) -> None:
        pending = await self._expenses.list_pending_approvals(ctx)
        contacts = await self._org.approver_external_ids(
            ctx.org_id, ctx.channel, exclude_user_id=ctx.user_id
        )
        text = (
            f"📥 {ctx.display_name} enviou um gasto para aprovação.\n"
            f"Você tem {len(pending)} gasto(s) a aprovar. Use /aprovacoes."
        )
        for external_id in contacts:
            await self._notifier.notify(ctx.channel, external_id, text)

    async def _notify_author(self, ctx, expense: Expense, text: str) -> None:
        external_id = await self._org.external_id_for(expense.user_id, ctx.channel)
        if external_id is not None:
            await self._notifier.notify(ctx.channel, external_id, text)

    async def _format_approval_item(self, e: Expense) -> str:
        author = await self._org.user_name(e.user_id) or f"usuário {e.user_id}"
        return f"#{e.id} • {author}\n{self._format_expense(e)}"

    # --- Relatórios ----------------------------------------------------------

    async def _reply_summary(self, ctx, arg, responder) -> None:
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

    async def _reply_recent(self, ctx, responder) -> None:
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
        lines = [
            f"📍 {e.store_name}",
            f"💰 R$ {e.total_amount:.2f}",
            f"📂 {e.category}",
            f"📅 Data: {e.date.strftime('%d/%m/%Y')}",
        ]
        if e.cost_center:
            lines.append(f"🏢 Centro de custo: {e.cost_center}")
        return "\n".join(lines)

    def _format_draft(self, e: Expense) -> str:
        return "Confira o gasto:\n\n" + self._format_expense(e) + "\n\nConfirmar ou editar?"

    @staticmethod
    def _start_message(name: str) -> str:
        return (
            f"Olá, {name}! 👋 Sou seu assistente de finanças.\n\n"
            "📸 Envie a foto de um comprovante (ou use /gasto para lançar por texto) — "
            "você confirma e pode editar categoria/centro de custo antes de salvar.\n\n"
            "🏢 Equipe:\n"
            "/criar_empresa <nome> - cria uma empresa (você vira admin)\n"
            "/entrar <código> - entra numa empresa pelo código\n"
            "/empresa - empresa ativa e papel | /empresas, /trocar <id>\n\n"
            "📂 Categorias/centros (admin): /add_categoria, /add_centro | /categorias, /centros\n\n"
            "💸 Gastos:\n"
            "/gasto <valor> <descrição> - lança um gasto por texto\n"
            "/listar - últimos gastos | /resumo [meses] - total do período\n\n"
            "🧾 Reembolso:\n"
            "/reembolsos - status dos seus gastos enviados\n"
            "/aprovacoes - fila de aprovação (aprovadores) | /rejeitar <id> <motivo>\n"
            "/aprovar <id>, /aprovar_todos, /reembolsar <id> (aprovadores)\n\n"
            "📊 Painel web: /login - link de acesso aos relatórios"
        )


def _to_int(value: str):
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
