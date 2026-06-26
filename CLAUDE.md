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

# Web dashboard SPA (React/Vite — lives in web/, consumes the API)
cd web && npm install && npm run dev   # :5173 ; `npm run build` typechecks + bundles
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

- `src/core/entities.py` — pure domain (Pydantic): `Organization(…, cnpj, address, cep)`, `User(…, cpf, bank_*, pix_key)`, `ChannelIdentity(user_id, channel, external_id)`, `Membership(role)`, `Expense(org_id, user_id, status, cost_center, nota_id, …)`, `NotaDebito(org_id, user_id, numero, competencia, status, vencimento, …)`, `Category`/`CostCenter`. `Expense` references the internal `user_id`, **never** a `telegram_id`. `Expense.date`/`NotaDebito.competencia` are real `date`s (the string→date boundary lives in the service). `ExpenseStatus` = `pending_review|confirmed`; `NotaStatus` = `aberta|fechada|aprovada|rejeitada|paga`.
- `src/core/ports/` — interfaces the core needs:
  - `messaging.py` — `MessagingChannel`, `IncomingMessage` (normalized, channel-neutral), `InteractivePrompt`/`PromptAction` (abstract "confirm/cancel" — no inline-keyboard assumption), `ChannelResponder`.
  - `notifications.py` — `Notifier`: **proactive push** to a user by `(channel, external_id)`, distinct from `ChannelResponder` (which replies inside an ongoing conversation). Used to ping approvers and notify the author of a decision. Returns `False` on undeliverable (never started the bot / blocked) so business flow never breaks on a missed push.
  - `repositories.py` — repository interfaces + `UnitOfWork`.
  - `ai.py` — `ExpenseExtractor` returning `ExtractedExpense` (raw, `date` still a `DD/MM/YYYY` string).
  - `storage.py` — `ReceiptStorage`.
  - `auth.py` — `TokenIssuer` (Fase 3): `issue(claims, ttl)` / `verify(token)`. Signed-token mechanism (JWT) is an adapter detail; tokens are self-contained so the bot can issue in one process and the API verify in another with no shared DB.
- `src/core/services/` — channel-neutral business logic, called by the bot today and the web API later:
  - `org_service.py` — `OrgService.resolve_context()` maps a channel identity to an internal `UserContext(user_id, org_id, display_name, channel)` where `org_id` is the user's **active org**, **auto-provisioning** user + personal org + membership + channel identity on first contact. Fase 1 added team onboarding: `create_organization` (creator = admin, generates a `join_code`, sets it active), `join_organization(code)` (member, sets active), `switch_active`, `list_organizations`, role checks (`is_admin`), and org-defined `add_category`/`add_cost_center` (admin-only, idempotent) + listings. Fase 2 added `approver_external_ids` / `external_id_for` / `user_name` to resolve who/where to push. Fase 5 added `set_payment_info` (CPF/banco/PIX no usuário) and `set_org_fiscal` (CNPJ/endereço/CEP na org, admin-only) + `get_user`/`get_org`.
  - `expense_service.py` — `ExpenseService`: extract → store receipt → save **draft** (`PENDING_REVIEW`) → `confirm()` → `cancel()`. Owns the string→date parse. Fase 1 added `create_manual_draft` (text via `/gasto`) and `set_category`/`set_cost_center`. **Fase 5** changed `confirm()`: it sets the expense to `CONFIRMED` and **attaches it to the author's open `NotaDebito`** (auto-creating one for the current month), returning `(expense, nota)`. The reimbursement lifecycle no longer lives on the expense — it moved to the nota. Photo extraction passes the org's category list so the AI **suggests within it**.
  - `nota_service.py` (Fase 5) — `NotaService`: the nota is the unit of reimbursement. `ensure_open`/`current_open` (the author's open nota), `list_for_user`/`list_for_org`, `get_with_items` (+ `include_others` for approvers), `close(approve_directly)` (assigns sequential `numero` + `vencimento` = 5th business day of next month; auto-approves if the author is an approver), and approver ops `list_pending`/`approve`/`reject(comment)`/`pay`. State transitions + org-scoping here; **role gating is enforced by the app**. `valor_a_pagar(nota, items)` = sum of items − retenções.
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

**Reimbursement flow (Fase 5 — note-centric).** The unit of reimbursement is the **nota de débito**, not the individual expense. Confirming a draft adds it as an item to the author's open nota (auto-created, competência = current month). The author closes the nota (`/nota_fechar`) → it gets a sequential `numero` + `vencimento` and goes to `FECHADA` (or straight to `APROVADA` if the author is an approver — frictionless personal use), pushing approvers. An approver works `/aprovacoes` (per-nota Aprovar/Rejeitar buttons) → `approve`/`reject(comment)`/`pay`; the author is pushed on each decision and tracks via `/notas`. **NotaStatus lifecycle:** `aberta → fechada → aprovada → paga`, or `fechada → rejeitada`. **ExpenseStatus** is now just `pending_review → confirmed` (an expense is a line item; its reimbursement state is the nota's). **Approver = admin/owner**; the app gates every approval action with `is_admin`. This replaces the Fase 2 per-expense approval flow (the issue #3 objetivo described exactly this note grouping).

Any change to the extracted-field set must stay consistent across: the Gemini prompt keys (`ai_engine.py`), `ExtractedExpense` (`ports/ai.py`), `Expense` (`entities.py`), the ORM model (`persistence/models.py`) + a new Alembic migration, and the confirmation formatting (`app.py`).

## Notes & gotchas

- **`alembic/env.py` runs async** through asyncpg and pulls the URL + metadata from `src.config`/the ORM models — there is no separate sync DB driver and no URL in `alembic.ini`.
- The interactive prompt is intentionally abstract: action keys are echoed back verbatim in `IncomingMessage.action`, so the flow is **stateless** (no in-memory session). The draft prompt offers `exp_ok`/`exp_no`/`exp_cat`/`exp_cc:<id>`; the category/cost-center pickers echo `setcat`/`setcc:<id>:<idx>` where `<idx>` indexes into the org's (deterministically ordered) category/cost-center list. The nota view adds `nt_close:<id>` (close & submit), `nt_ok:<id>` (approve), `nt_no:<id>` (start reject), `nt_pay:<id>` (mark paid). A WhatsApp adapter would map the same keys to its own button primitives.
- **Mandatory rejection comment, kept stateless**: because there's no session to stash "I'm rejecting nota #X, now waiting for the reason", tapping ❌ Rejeitar doesn't collect free text — it instructs the approver to send `/nota_rejeitar <id> <motivo>`, which carries both id and comment in one stateless message. `NotaService.reject()` requires a non-empty comment (validated in the app).
- **Active org**: a user can belong to many orgs (auto-created personal org + joined companies). `User.active_org_id` decides where expenses land; `/criar_empresa` and `/entrar` switch it, `/trocar` changes it, `/empresa` shows it. `resolve_context` returns the active org, falling back to the oldest membership if unset.
- **Bot commands** live only as routing in `app.py._handle_text` (a command→handler dict): `/start`, `/gasto`, `/listar`, `/resumo`, `/criar_empresa`, `/entrar`, `/empresa`, `/empresas`, `/trocar`, `/categorias`, `/add_categoria`, `/centros`, `/add_centro`, (Fase 5) `/nota`, `/notas`, `/nota_fechar`, `/aprovacoes`, `/nota_aprovar`, `/nota_rejeitar`, `/nota_pagar`, `/meus_dados`, `/empresa_dados`, and (Fase 3) `/login` (envia o magic-link do painel web). The Telegram adapter just forwards text; it has no command knowledge.
- `src/adapters/spreadsheet.py` (Google Sheets) is **still not wired** and predates Fase 0 — treat as legacy/unused. Fase 3 shipped **backend-first** (API + channel auth + JSON reports + CSV export) and **deferred** the React/Vite SPA, web approvals, and Google Sheets/PDF export; wiring this adapter behind a port belongs to that deferred export work.
- **Web auth (Fase 3)** is stateless and channel-mediated: `/login` in the bot issues a short login JWT inside a magic-link to `WEB_BASE_URL/login?token=…`; the SPA calls `POST /auth/exchange` to swap it for a session JWT (Bearer). No sessions table. Report endpoints are **admin/owner only** — the panel is the manager's view; employees stay in the chat. Aggregation is done in Python in `ReportService` over `CONFIRMED` items (fine for MVP volumes; swap for SQL GROUP BY if it grows); the `status` query filters by **nota status** (e.g. `aprovada`/`paga`) via a join. Fase 5 added `GET /notas` (manager → org notas, member → own) and `GET /notas/{id}` (items + totais).
- **`web/` (SPA, React + Vite + TS)** is a standalone frontend, **not** wired into the Python build — its own `package.json`/`npm`. Talks to the API at `VITE_API_URL` (default `http://localhost:8000`), session JWT in `localStorage`. `App.tsx` is the auth bootstrap (reads `?token=` from the magic-link → `exchange` → `getMe`; 401 → re-login gate, non-admin → "painel dos gestores"); `Dashboard.tsx` is the manager view (hero total + de/até/status filters + ledger-style ranked bars per category/cost-center/user/month + CSV). No charting lib — bars are plain CSS. Fonts via Google Fonts `<link>` (swap to bundled if offline rendering is needed). The known npm-audit warnings are the esbuild dev-server advisory (Vite), dev-only.
- `google-generativeai` is deprecated upstream (warns on import); a future task may migrate to `google-genai`. Out of Fase 0 scope.
- The `Expense.date` (domain `date`) vs ORM `date_at` column split is deliberate; `ExtractedExpense.date` is the only string form, parsed in `ExpenseService`.
