"""Roteador de aplicação — cola neutra de canal entre o port de mensagens e os serviços.

Implementa a assinatura `MessageHandler`: recebe `IncomingMessage` + `ChannelResponder`
e orquestra `OrgService`/`ExpenseService`/`NotaService`. Não conhece Telegram nem
WhatsApp — só fala em termos de mensagens normalizadas e prompts interativos abstratos.

A partir da Fase 5 o ciclo de reembolso pertence à **nota de débito**: gastos
confirmados viram itens da nota aberta; a nota é fechada e aprovada/paga como unidade.
"""
import re
from datetime import date
from typing import Optional

from src.core.entities import Expense, NotaDebito, NotaStatus, Role
from src.core.ports.messaging import (
    ChannelResponder,
    IncomingMessage,
    InteractivePrompt,
    PromptAction,
)
from src.core.ports.notifications import Notifier
from src.core.services.auth_service import AuthService
from src.core.services.expense_service import ExpenseService
from src.core.services.nota_service import NotaService, valor_a_pagar
from src.core.services.org_service import OrgService, UserContext
from src.logging_config import get_logger

log = get_logger(__name__)

# Chaves de ação neutras devolvidas pelos prompts (cabem nos 64 bytes do Telegram).
_CONFIRM = "exp_ok"
_DELETE = "exp_no"
_OPEN_CAT = "exp_cat"   # abre o seletor de categoria
_OPEN_CC = "exp_cc"     # abre o seletor de centro de custo
_SET_CAT = "setcat"     # setcat:<id>:<idx>
_SET_CC = "setcc"       # setcc:<id>:<idx>
_NT_CLOSE = "nt_close"  # fecha e envia a nota:    nt_close:<id>
_NT_OK = "nt_ok"        # aprova a nota:           nt_ok:<id>
_NT_NO = "nt_no"        # inicia rejeição da nota: nt_no:<id>
_NT_PAY = "nt_pay"      # marca a nota como paga:  nt_pay:<id>

_NOTA_LABELS = {
    NotaStatus.ABERTA: "📂 aberta",
    NotaStatus.FECHADA: "⏳ aguardando aprovação",
    NotaStatus.APROVADA: "✅ aprovada",
    NotaStatus.REJEITADA: "❌ rejeitada",
    NotaStatus.PAGA: "💸 paga",
}
_MESES = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]


class BotApplication:
    def __init__(
        self,
        org_service: OrgService,
        expense_service: ExpenseService,
        nota_service: NotaService,
        notifier: Notifier,
        auth_service: Optional[AuthService] = None,
        web_base_url: str = "",
    ):
        self._org = org_service
        self._expenses = expense_service
        self._notas = nota_service
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
            "nota": lambda: self._show_nota(ctx, rest, responder),
            "notas": lambda: self._list_notas(ctx, responder),
            "nota_fechar": lambda: self._close_current_nota(ctx, responder),
            "aprovacoes": lambda: self._list_pending_notas(ctx, responder),
            "nota_aprovar": lambda: self._approve_nota_cmd(ctx, rest, responder),
            "nota_rejeitar": lambda: self._reject_nota_cmd(ctx, rest, responder),
            "nota_pagar": lambda: self._pay_nota_cmd(ctx, rest, responder),
            "meus_dados": lambda: self._my_data(ctx, rest, responder),
            "empresa_dados": lambda: self._org_data(ctx, rest, responder),
            "login": lambda: self._web_login(ctx, responder),
        }
        handler = handlers.get(command)
        if handler:
            await handler()
        else:
            await responder.send_text(
                "Envie a foto de um comprovante, ou use /gasto, /nota, /notas, "
                "/resumo, /empresa ou /start."
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
            f"Seus gastos agora vão para esta empresa. Defina os dados fiscais com /empresa_dados."
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

    # --- Gastos (rascunho → item da nota) -----------------------------------

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
        elif verb == _NT_CLOSE:
            await self._close_nota(ctx, _to_int(args), responder)
        elif verb == _NT_OK:
            await self._approve_nota(ctx, _to_int(args), responder)
        elif verb == _NT_NO:
            await self._prompt_reject_nota(ctx, _to_int(args), responder)
        elif verb == _NT_PAY:
            await self._pay_nota(ctx, _to_int(args), responder)

    async def _confirm_draft(self, ctx, expense_id, responder) -> None:
        result = await self._expenses.confirm(ctx, expense_id)
        if result is None:
            await responder.send_text("Não encontrei esse rascunho para confirmar.")
            return
        expense, nota = result
        await responder.send_text(
            f"✅ Adicionado à sua nota de débito de {self._competencia(nota)}.\n"
            f"{self._format_expense(expense)}\n\n"
            "Veja a nota em /nota. Quando terminar o mês, feche com /nota_fechar."
        )

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
        await self._send_draft_prompt(ctx, updated, responder)

    # --- Nota de débito (autor) ---------------------------------------------

    async def _show_nota(self, ctx, arg, responder) -> None:
        is_admin = await self._org.is_admin(ctx)
        if arg.strip():
            nota_id = _to_int(arg)
            if nota_id is None:
                await responder.send_text("Use: /nota (nota aberta) ou /nota <id>")
                return
            result = await self._notas.get_with_items(ctx, nota_id, include_others=is_admin)
        else:
            nota = await self._notas.current_open(ctx)
            if nota is None:
                await responder.send_text(
                    "Você não tem nota aberta. Envie um comprovante ou use /gasto para começar uma."
                )
                return
            result = await self._notas.get_with_items(ctx, nota.id)
        if result is None:
            await responder.send_text("Nota não encontrada.")
            return
        nota, items = result
        author = await self._org.user_name(nota.user_id) if is_admin else None
        await self._send_nota(nota, items, responder, is_admin=is_admin, author=author)

    async def _list_notas(self, ctx, responder) -> None:
        notas = await self._notas.list_for_user(ctx)
        if not notas:
            await responder.send_text("Você ainda não tem notas de débito. Comece lançando um gasto.")
            return
        lines = ["🧾 Suas notas de débito (use /nota <id>):\n"]
        for n in notas:
            num = f"#{n.numero}" if n.numero else "(rascunho)"
            lines.append(f"[{n.id}] {num} {self._competencia(n)} — {_NOTA_LABELS[n.status]}")
        await responder.send_text("\n".join(lines))

    async def _close_current_nota(self, ctx, responder) -> None:
        nota = await self._notas.current_open(ctx)
        if nota is None:
            await responder.send_text("Você não tem nota aberta para fechar.")
            return
        await self._close_nota(ctx, nota.id, responder)

    async def _close_nota(self, ctx, nota_id, responder) -> None:
        if nota_id is None:
            return
        result = await self._notas.get_with_items(ctx, nota_id)
        if result is None:
            await responder.send_text("Nota não encontrada.")
            return
        nota, items = result
        if nota.status != NotaStatus.ABERTA:
            await responder.send_text("Essa nota já foi fechada.")
            return
        if not items:
            await responder.send_text("Sua nota está vazia. Adicione ao menos um gasto antes de fechar.")
            return
        is_admin = await self._org.is_admin(ctx)
        saved = await self._notas.close(ctx, nota_id, approve_directly=is_admin)
        if saved is None:
            await responder.send_text("Não consegui fechar a nota.")
            return
        if saved.status == NotaStatus.APROVADA:
            await responder.send_text(
                f"✅ Nota de débito #{saved.numero} fechada e aprovada (você é aprovador)."
            )
        else:
            await responder.send_text(
                f"📤 Nota de débito #{saved.numero} fechada e enviada para aprovação.\n"
                f"Vencimento: {saved.vencimento.strftime('%d/%m/%Y')}. Acompanhe em /notas."
            )
            await self._notify_approvers(ctx)

    # --- Nota de débito (aprovador) -----------------------------------------

    async def _list_pending_notas(self, ctx, responder) -> None:
        if not await self._require_approver(ctx, responder):
            return
        pending = await self._notas.list_pending(ctx)
        if not pending:
            await responder.send_text("✅ Nenhuma nota aguardando aprovação.")
            return
        await responder.send_text(f"📋 {len(pending)} nota(s) aguardando aprovação:")
        for nota in pending:
            result = await self._notas.get_with_items(ctx, nota.id, include_others=True)
            if result is None:
                continue
            n, items = result
            author = await self._org.user_name(n.user_id)
            await self._send_nota(n, items, responder, is_admin=True, author=author)

    async def _approve_nota_cmd(self, ctx, rest, responder) -> None:
        nota_id = _to_int(rest)
        if nota_id is None:
            await responder.send_text("Use: /nota_aprovar <id> (veja /aprovacoes)")
            return
        await self._approve_nota(ctx, nota_id, responder)

    async def _approve_nota(self, ctx, nota_id, responder) -> None:
        if not await self._require_approver(ctx, responder):
            return
        saved = await self._notas.approve(ctx, nota_id)
        if saved is None:
            await responder.send_text("Essa nota não está mais aguardando aprovação.")
            return
        await responder.send_text(f"✅ Nota de débito #{saved.numero} aprovada.")
        await self._notify_author(
            ctx, saved, f"✅ Sua nota de débito #{saved.numero} foi aprovada."
        )

    async def _prompt_reject_nota(self, ctx, nota_id, responder) -> None:
        if not await self._require_approver(ctx, responder):
            return
        if nota_id is None:
            return
        await responder.send_text(
            f"Para rejeitar a nota #{nota_id}, envie o motivo:\n/nota_rejeitar {nota_id} <motivo>"
        )

    async def _reject_nota_cmd(self, ctx, rest, responder) -> None:
        if not await self._require_approver(ctx, responder):
            return
        id_str, _, comment = rest.partition(" ")
        nota_id = _to_int(id_str)
        comment = comment.strip()
        if nota_id is None or not comment:
            await responder.send_text("Use: /nota_rejeitar <id> <motivo>. O motivo é obrigatório.")
            return
        saved = await self._notas.reject(ctx, nota_id, comment)
        if saved is None:
            await responder.send_text("Essa nota não está mais aguardando aprovação.")
            return
        await responder.send_text(f"❌ Nota de débito #{saved.numero} rejeitada.\nMotivo: {comment}")
        await self._notify_author(
            ctx, saved, f"❌ Sua nota de débito #{saved.numero} foi rejeitada.\nMotivo: {comment}"
        )

    async def _pay_nota_cmd(self, ctx, rest, responder) -> None:
        nota_id = _to_int(rest)
        if nota_id is None:
            await responder.send_text("Use: /nota_pagar <id>")
            return
        await self._pay_nota(ctx, nota_id, responder)

    async def _pay_nota(self, ctx, nota_id, responder) -> None:
        if not await self._require_approver(ctx, responder):
            return
        saved = await self._notas.pay(ctx, nota_id)
        if saved is None:
            await responder.send_text("Só dá para pagar uma nota já aprovada.")
            return
        await responder.send_text(f"💸 Nota de débito #{saved.numero} marcada como paga.")
        await self._notify_author(
            ctx, saved, f"💸 Sua nota de débito #{saved.numero} foi paga."
        )

    async def _require_approver(self, ctx, responder) -> bool:
        if await self._org.is_admin(ctx):
            return True
        await responder.send_text("Apenas aprovadores (admin/owner) da empresa podem fazer isso.")
        return False

    # --- Dados fiscais / de pagamento ---------------------------------------

    async def _my_data(self, ctx, rest, responder) -> None:
        kv = _parse_kv(rest, ["CPF", "PIX", "BANCO", "AG", "CONTA"])
        if not kv:
            u = await self._org.get_user(ctx.user_id)
            await responder.send_text(
                "💳 Seus dados de pagamento (na nota de débito):\n"
                f"CPF: {u.cpf or '—'}\nPIX: {u.pix_key or '—'}\n"
                f"Banco: {u.bank_name or '—'} | Ag: {u.bank_agency or '—'} | Conta: {u.bank_account or '—'}\n\n"
                "Para definir: /meus_dados CPF=000 PIX=... BANCO=... AG=... CONTA=..."
            )
            return
        await self._org.set_payment_info(
            ctx,
            cpf=kv.get("CPF"),
            pix_key=kv.get("PIX"),
            bank_name=kv.get("BANCO"),
            bank_agency=kv.get("AG"),
            bank_account=kv.get("CONTA"),
        )
        await responder.send_text("✅ Dados de pagamento atualizados.")

    async def _org_data(self, ctx, rest, responder) -> None:
        kv = _parse_kv(rest, ["CNPJ", "ENDERECO", "CEP"])
        if not kv:
            o = await self._org.get_org(ctx.org_id)
            await responder.send_text(
                "🏢 Dados fiscais da empresa (tomadora na nota):\n"
                f"CNPJ: {o.cnpj or '—'}\nEndereço: {o.address or '—'}\nCEP: {o.cep or '—'}\n\n"
                "Admin define: /empresa_dados CNPJ=... ENDERECO=... CEP=..."
            )
            return
        saved = await self._org.set_org_fiscal(
            ctx, cnpj=kv.get("CNPJ"), address=kv.get("ENDERECO"), cep=kv.get("CEP")
        )
        await responder.send_text(
            "✅ Dados fiscais da empresa atualizados." if saved
            else "Apenas admins podem editar os dados da empresa."
        )

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

    # --- Notificações push ---------------------------------------------------

    async def _notify_approvers(self, ctx) -> None:
        pending = await self._notas.list_pending(ctx)
        contacts = await self._org.approver_external_ids(
            ctx.org_id, ctx.channel, exclude_user_id=ctx.user_id
        )
        text = (
            f"📥 {ctx.display_name} enviou uma nota de débito para aprovação.\n"
            f"Você tem {len(pending)} nota(s) a aprovar. Use /aprovacoes."
        )
        for external_id in contacts:
            await self._notifier.notify(ctx.channel, external_id, text)

    async def _notify_author(self, ctx, nota: NotaDebito, text: str) -> None:
        external_id = await self._org.external_id_for(nota.user_id, ctx.channel)
        if external_id is not None:
            await self._notifier.notify(ctx.channel, external_id, text)

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
        lines = ["📋 Últimos gastos:\n"]
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
    def _competencia(nota: NotaDebito) -> str:
        return f"{_MESES[nota.competencia.month - 1]}/{nota.competencia.year}"

    async def _send_nota(self, nota, items, responder, *, is_admin: bool, author=None) -> None:
        """Renderiza a nota e oferece os botões adequados ao estado e ao papel."""
        num = f"#{nota.numero}" if nota.numero else "(rascunho)"
        lines = [f"🧾 Nota de débito {num} — {self._competencia(nota)}"]
        if author:
            lines.append(f"Emitente: {author}")
        lines.append(f"Status: {_NOTA_LABELS[nota.status]}")
        if nota.vencimento:
            lines.append(f"Vencimento: {nota.vencimento.strftime('%d/%m/%Y')}")
        lines.append("\nItens:")
        for e in items:
            extra = f" ({e.category}" + (f"/{e.cost_center})" if e.cost_center else ")")
            lines.append(f"• {e.date.strftime('%d/%m')} {e.store_name} — R$ {e.total_amount:.2f}{extra}")
        if not items:
            lines.append("• (nenhum gasto ainda)")
        if nota.outras_retencoes:
            lines.append(f"\nRetenções/descontos: R$ {nota.outras_retencoes:.2f}")
        lines.append(f"\n💰 Valor a pagar: R$ {valor_a_pagar(nota, items):.2f}")
        if nota.status == NotaStatus.REJEITADA and nota.decision_comment:
            lines.append(f"↳ motivo: {nota.decision_comment}")

        actions = []
        if nota.status == NotaStatus.ABERTA and not is_admin:
            actions.append(PromptAction(f"{_NT_CLOSE}:{nota.id}", "✅ Fechar e enviar"))
        elif nota.status == NotaStatus.ABERTA and is_admin:
            actions.append(PromptAction(f"{_NT_CLOSE}:{nota.id}", "✅ Fechar e aprovar"))
        if is_admin and nota.status == NotaStatus.FECHADA:
            actions.append(PromptAction(f"{_NT_OK}:{nota.id}", "✅ Aprovar"))
            actions.append(PromptAction(f"{_NT_NO}:{nota.id}", "❌ Rejeitar"))
        if is_admin and nota.status == NotaStatus.APROVADA:
            actions.append(PromptAction(f"{_NT_PAY}:{nota.id}", "💸 Marcar paga"))

        text = "\n".join(lines)
        if actions:
            await responder.send_prompt(InteractivePrompt(text=text, actions=actions))
        else:
            await responder.send_text(text)

    @staticmethod
    def _start_message(name: str) -> str:
        return (
            f"Olá, {name}! 👋 Sou seu assistente de finanças.\n\n"
            "📸 Envie a foto de um comprovante (ou use /gasto) — você confirma e o gasto "
            "entra na sua nota de débito do mês.\n\n"
            "🧾 Nota de débito:\n"
            "/nota - sua nota aberta | /notas - todas as suas notas\n"
            "/nota_fechar - fecha e envia a nota do mês para aprovação\n\n"
            "✅ Aprovação (admin):\n"
            "/aprovacoes - notas a aprovar | /nota_aprovar <id> | /nota_rejeitar <id> <motivo>\n"
            "/nota_pagar <id> - marca como paga\n\n"
            "🏢 Equipe: /criar_empresa, /entrar <código>, /empresa, /empresas, /trocar <id>\n"
            "📂 Categorias/centros (admin): /add_categoria, /add_centro | /categorias, /centros\n"
            "💳 Dados da nota: /meus_dados (CPF/banco/PIX) | /empresa_dados (CNPJ/endereço)\n"
            "📈 /listar, /resumo [meses] | 📊 painel web: /login"
        )


def _parse_kv(text: str, keys: list[str]) -> dict:
    """Extrai pares `CHAVE=valor` de um texto livre (valores podem ter espaços)."""
    if not text.strip():
        return {}
    alt = "|".join(keys)
    pattern = re.compile(
        rf"({alt})\s*=\s*(.*?)(?=\s+(?:{alt})\s*=|$)", re.IGNORECASE | re.DOTALL
    )
    return {mt.group(1).upper(): mt.group(2).strip() for mt in pattern.finditer(text)}


def _to_int(value: str):
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
