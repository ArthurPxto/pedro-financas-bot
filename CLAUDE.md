# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Pedro Finanças is a multi-tenant expense bot. A user sends a photo of a receipt; Google Gemini (multimodal) extracts the fields; the user **confirms before saving**; the expense is stored per organization/user in PostgreSQL with the receipt image kept for audit. The UI language (bot messages, commands) is Brazilian Portuguese.

As of Fase 0 the codebase follows **ports & adapters (hexagonal)**: the business core has no knowledge of Telegram. A new channel (e.g. WhatsApp) is added by writing a new adapter — never by touching `core/`.

## Commands

```bash
# Environment (uv — there is no system pip/venv module)
uv venv --python 3.14 .venv
uv pip install -r requirements.txt --python .venv

# Local PostgreSQL
docker compose up -d                 # postgres:16 on localhost:5432 (pedro/pedro)

# Migrations (Alembic runs async via asyncpg; URL comes from src.config, not alembic.ini)
.venv/bin/alembic upgrade head
.venv/bin/alembic revision --autogenerate -m "msg"

# Run the bot (must run as a module from repo root — uses `src.` absolute imports)
.venv/bin/python -m src.main

# Run the web API (Fase 3 — separate process, same DB/services; needs WEB_JWT_SECRET)
.venv/bin/python -m src.api
```

There is no automated test suite or linter configured. `requirements.txt` is a fully-pinned flat freeze (`uv pip freeze`), not a curated direct-deps file.

### Required environment (`.env` in repo root, not versioned)

See `.env.example`. Config is read **once at boot** by `src/config.py` (pydantic-settings) and validated — a missing required var fails at startup, not mid-flow. No other module calls `os.getenv`.

- `TELEGRAM_TOKEN`, `GEMINI_API_KEY` — required.
- `DATABASE_URL` — async DSN, e.g. `postgresql+asyncpg://pedro:pedro@localhost:5432/pedro_financas`.
- `GEMINI_MODEL`, `RECEIPT_STORAGE_*`, `LOG_LEVEL`, `LOG_JSON` — optional, have defaults.
- `WEB_JWT_SECRET` — optional for the bot, **required for `src.api` and the `/login` command**. `WEB_BASE_URL`, `WEB_CORS_ORIGINS`, `API_HOST`, `API_PORT` — optional, have defaults. The bot boots without `WEB_JWT_SECRET`; `/login` just replies "painel não configurado".

## Architecture (hexagonal — the dependency rule is the contract)

The core depends only on its own ports; adapters depend on the core; the composition root depends on everything. **Core never imports an adapter.**

- `src/core/entities.py` — pure domain (Pydantic): `Organization`, `User`, `ChannelIdentity(user_id, channel, external_id)`, `Membership(role)`, `Expense(org_id, user_id, status, receipt_url, cost_center, …)`, `Category`. `Expense` references the internal `user_id`, **never** a `telegram_id`. `Expense.date` is a real `date` here (the string→date boundary lives in the service).
- `src/core/ports/` — interfaces the core needs:
  - `messaging.py` — `MessagingChannel`, `IncomingMessage` (normalized, channel-neutral), `InteractivePrompt`/`PromptAction` (abstract "confirm/cancel" — no inline-keyboard assumption), `ChannelResponder`.
  - `notifications.py` — `Notifier`: **proactive push** to a user by `(channel, external_id)`, distinct from `ChannelResponder` (which replies inside an ongoing conversation). Used to ping approvers and notify the author of a decision. Returns `False` on undeliverable (never started the bot / blocked) so business flow never breaks on a missed push.
  - `repositories.py` — repository interfaces + `UnitOfWork`.
  - `ai.py` — `ExpenseExtractor` returning `ExtractedExpense` (raw, `date` still a `DD/MM/YYYY` string).
  - `storage.py` — `ReceiptStorage`.
  - `auth.py` — `TokenIssuer` (Fase 3): `issue(claims, ttl)` / `verify(token)`. Signed-token mechanism (JWT) is an adapter detail; tokens are self-contained so the bot can issue in one process and the API verify in another with no shared DB.
- `src/core/services/` — channel-neutral business logic, called by the bot today and the web API later:
  - `org_service.py` — `OrgService.resolve_context()` maps a channel identity to an internal `UserContext(user_id, org_id, display_name, channel)` where `org_id` is the user's **active org**, **auto-provisioning** user + personal org + membership + channel identity on first contact. Fase 1 added team onboarding: `create_organization` (creator = admin, generates a `join_code`, sets it active), `join_organization(code)` (member, sets active), `switch_active`, `list_organizations`, role checks (`is_admin`), and org-defined `add_category`/`add_cost_center` (admin-only, idempotent) + listings. Fase 2 added `approver_external_ids` / `external_id_for` / `user_name` to resolve who/where to push.
  - `expense_service.py` — `ExpenseService`: extract → store receipt → save **draft** (`PENDING_REVIEW`) → `confirm()` → `cancel()`. Owns the string→date parse. Fase 1 added `create_manual_draft` (text via `/gasto`) and `set_category`/`set_cost_center`. **Fase 2** turned `confirm` into the reimbursement entry point: `confirm(ctx, id, approve_directly)` sends a member's expense to `SUBMITTED` and an approver's straight to `APPROVED`; then `approve` / `reject(comment)` / `approve_all` (batch) / `mark_reimbursed`, plus `list_pending_approvals` and `list_my_reimbursements`. State transitions and org-scoping live here; **role gating is enforced by the app** before calling these. Photo extraction passes the org's category list so the AI **suggests within it**.
- `src/core/services/` (cont.)
  - `auth_service.py` (Fase 3) — `AuthService`: login por magic-link enviado pelo canal. `create_login_token(user_id)` (curto, 10 min) → `exchange(login_token)` devolve um token de sessão (7 dias) → `verify_session(token)` → `user_id`. Stateless (claim `purpose` separa login de sessão); depende só do `TokenIssuer`.
  - `report_service.py` (Fase 3) — `ReportService`: `overview(org_id, ReportFilter)` busca os gastos filtrados uma vez e **agrega em Python** (por categoria/centro/pessoa/mês, total/contagem); `list_for_export` devolve as linhas para o CSV. Mesma camada de persistência do bot, sem duplicar regra.
- `src/adapters/`
  - `ai_engine.py` — `GeminiExpenseExtractor` (Gemini `gemini-2.5-flash`; sync SDK run via `asyncio.to_thread`).
  - `security/jwt_issuer.py` (Fase 3) — `JwtTokenIssuer` implementando `TokenIssuer` via PyJWT (HS256). Toda dependência de `jwt` fica aqui.
  - `web/api.py` (Fase 3) — `create_api(...)` monta o FastAPI (driving adapter, irmão do `TelegramChannel`): `POST /auth/exchange`, `GET /auth/me`, `GET /reports/overview`, `GET /reports/export.csv`. Auth por Bearer (`HTTPBearer` → `AuthService.verify_session` → `OrgService.web_context`); relatórios exigem admin/owner. **Sem regra de negócio** — só traduz HTTP ⇄ serviços. CORS aberto (Bearer, sem cookies), pensado para uma SPA React/Vite consumir.
  - `storage/filesystem.py` — `FilesystemReceiptStorage` (returns a `file://…` `receipt_url`; swap for S3 later = new adapter only).
  - `persistence/` — `models.py` (SQLAlchemy ORM, separate from domain), `database.py` (async engine/session), `repositories.py` (SQLAlchemy repos + `UnitOfWork`, ORM⇄domain mapping).
  - `messaging/telegram_adapter.py` — `TelegramChannel` implementing **both** `MessagingChannel` and `Notifier` (it owns the bot, so it can also push). **All `python-telegram-bot` lives here.** Handlers only translate update ⇄ `IncomingMessage`; long polling is an internal detail (`run()` is sync and owns its loop). `notify()` sends to `chat_id=int(external_id)` (private chat id == Telegram user id).
- `src/app.py` — `BotApplication`: channel-neutral router implementing the `MessageHandler` signature. Coordinates services and emits interactive prompts. This (not the Telegram adapter) holds the photo→confirm→save orchestration.
- `src/main.py` — composition root of the **bot**. Builds adapters, injects into services + `BotApplication`, wires the handler into the channel, runs. The `TelegramChannel` is built **before** the services because it doubles as the `Notifier` injected into `BotApplication`. The `AuthService` is wired in only if `WEB_JWT_SECRET` is set (enables `/login`). No business logic, no import-time singletons.
- `src/api.py` (Fase 3) — composition root of the **web API**, a **separate process** sharing the same DB and services. Builds the engine/services + `JwtTokenIssuer`, calls `create_api`, runs uvicorn. Fails fast if `WEB_JWT_SECRET` is missing.

### Photo-to-expense flow (the core path)

Telegram update → `TelegramChannel` normalizes to `IncomingMessage` (media bytes downloaded by the adapter) → `BotApplication.handle` → `OrgService.resolve_context` → `ExpenseService.create_draft_from_image` (Gemini extract + receipt stored + draft `PENDING_REVIEW`) → `BotApplication` emits an `InteractivePrompt` (Confirmar/Cancelar) → user taps → adapter sends an `IncomingMessage` with `action="exp_ok:<id>"`/`"exp_no:<id>"` → `ExpenseService.confirm`/`cancel`.

**Reimbursement flow (Fase 2)** continues from `confirm`: a member's confirmed expense becomes `SUBMITTED` and the app pushes approvers ("Você tem N gastos a aprovar"); an admin/owner's own confirm auto-approves (`APPROVED`) so personal use stays frictionless. An approver works the queue via `/aprovacoes` (per-item Aprovar/Rejeitar buttons + an "Aprovar todos" batch button) → `approve`/`approve_all`/`reject`/`mark_reimbursed`; the author is pushed on each decision and tracks it via `/reembolsos`. Lifecycle: `pending_review → submitted → approved → reimbursed`, or `submitted → rejected`. **Approver = admin/owner** (no separate role); the app gates every approval action with `is_admin` before the service runs.

Any change to the extracted-field set must stay consistent across: the Gemini prompt keys (`ai_engine.py`), `ExtractedExpense` (`ports/ai.py`), `Expense` (`entities.py`), the ORM model (`persistence/models.py`) + a new Alembic migration, and the confirmation formatting (`app.py`).

## Notes & gotchas

- **`alembic/env.py` runs async** through asyncpg and pulls the URL + metadata from `src.config`/the ORM models — there is no separate sync DB driver and no URL in `alembic.ini`.
- The interactive prompt is intentionally abstract: action keys are echoed back verbatim in `IncomingMessage.action`, so the flow is **stateless** (no in-memory session). The draft prompt offers `exp_ok`/`exp_no`/`exp_cat`/`exp_cc:<id>`; the category/cost-center pickers echo `setcat`/`setcc:<id>:<idx>` where `<idx>` indexes into the org's (deterministically ordered) category/cost-center list. The approval queue adds `apv_ok:<id>` / `apv_no:<id>` / `apv_all` / `apv_reimb:<id>`. A WhatsApp adapter would map the same keys to its own button primitives.
- **Mandatory rejection comment, kept stateless**: because there's no session to stash "I'm rejecting #X, now waiting for the reason", tapping ❌ Rejeitar doesn't collect free text — it instructs the approver to send `/rejeitar <id> <motivo>`, which carries both id and comment in one stateless message. `reject()` requires a non-empty comment (validated in the app).
- **Active org**: a user can belong to many orgs (auto-created personal org + joined companies). `User.active_org_id` decides where expenses land; `/criar_empresa` and `/entrar` switch it, `/trocar` changes it, `/empresa` shows it. `resolve_context` returns the active org, falling back to the oldest membership if unset.
- **Bot commands** live only as routing in `app.py._handle_text` (a command→handler dict): `/start`, `/gasto`, `/listar`, `/resumo`, `/criar_empresa`, `/entrar`, `/empresa`, `/empresas`, `/trocar`, `/categorias`, `/add_categoria`, `/centros`, `/add_centro`, (Fase 2) `/reembolsos`, `/aprovacoes`, `/aprovar`, `/aprovar_todos`, `/rejeitar`, `/reembolsar`, and (Fase 3) `/login` (envia o magic-link do painel web). The Telegram adapter just forwards text; it has no command knowledge.
- `src/adapters/spreadsheet.py` (Google Sheets) is **still not wired** and predates Fase 0 — treat as legacy/unused. Fase 3 shipped **backend-first** (API + channel auth + JSON reports + CSV export) and **deferred** the React/Vite SPA, web approvals, and Google Sheets/PDF export; wiring this adapter behind a port belongs to that deferred export work.
- **Web auth (Fase 3)** is stateless and channel-mediated: `/login` in the bot issues a short login JWT inside a magic-link to `WEB_BASE_URL/login?token=…`; the SPA calls `POST /auth/exchange` to swap it for a session JWT (Bearer). No sessions table. Report endpoints are **admin/owner only** — the panel is the manager's view; employees stay in the chat. Aggregation is done in Python in `ReportService` (fine for MVP volumes; swap for SQL GROUP BY if it grows).
- `google-generativeai` is deprecated upstream (warns on import); a future task may migrate to `google-genai`. Out of Fase 0 scope.
- The `Expense.date` (domain `date`) vs ORM `date_at` column split is deliberate; `ExtractedExpense.date` is the only string form, parsed in `ExpenseService`.
