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
```

There is no automated test suite or linter configured. `requirements.txt` is a fully-pinned flat freeze (`uv pip freeze`), not a curated direct-deps file.

### Required environment (`.env` in repo root, not versioned)

See `.env.example`. Config is read **once at boot** by `src/config.py` (pydantic-settings) and validated — a missing required var fails at startup, not mid-flow. No other module calls `os.getenv`.

- `TELEGRAM_TOKEN`, `GEMINI_API_KEY` — required.
- `DATABASE_URL` — async DSN, e.g. `postgresql+asyncpg://pedro:pedro@localhost:5432/pedro_financas`.
- `GEMINI_MODEL`, `RECEIPT_STORAGE_*`, `LOG_LEVEL`, `LOG_JSON` — optional, have defaults.

## Architecture (hexagonal — the dependency rule is the contract)

The core depends only on its own ports; adapters depend on the core; the composition root depends on everything. **Core never imports an adapter.**

- `src/core/entities.py` — pure domain (Pydantic): `Organization`, `User`, `ChannelIdentity(user_id, channel, external_id)`, `Membership(role)`, `Expense(org_id, user_id, status, receipt_url, cost_center, …)`, `Category`. `Expense` references the internal `user_id`, **never** a `telegram_id`. `Expense.date` is a real `date` here (the string→date boundary lives in the service).
- `src/core/ports/` — interfaces the core needs:
  - `messaging.py` — `MessagingChannel`, `IncomingMessage` (normalized, channel-neutral), `InteractivePrompt`/`PromptAction` (abstract "confirm/cancel" — no inline-keyboard assumption), `ChannelResponder`.
  - `repositories.py` — repository interfaces + `UnitOfWork`.
  - `ai.py` — `ExpenseExtractor` returning `ExtractedExpense` (raw, `date` still a `DD/MM/YYYY` string).
  - `storage.py` — `ReceiptStorage`.
- `src/core/services/` — channel-neutral business logic, called by the bot today and the web API later:
  - `org_service.py` — `OrgService.resolve_context()` maps a channel identity to an internal `UserContext(user_id, org_id)` where `org_id` is the user's **active org**, **auto-provisioning** user + personal org + membership + channel identity on first contact. Fase 1 added team onboarding: `create_organization` (creator = admin, generates a `join_code`, sets it active), `join_organization(code)` (member, sets active), `switch_active`, `list_organizations`, role checks (`is_admin`), and org-defined `add_category`/`add_cost_center` (admin-only, idempotent) + listings.
  - `expense_service.py` — `ExpenseService`: extract → store receipt → save **draft** (`PENDING_REVIEW`) → `confirm()` (→ `REGISTERED`) / `cancel()`. Owns the string→date parse. Fase 1 added `create_manual_draft` (text entry via `/gasto`), and `set_category`/`set_cost_center` editing a pending draft. Photo extraction passes the org's category list so the AI **suggests within it**.
- `src/adapters/`
  - `ai_engine.py` — `GeminiExpenseExtractor` (Gemini `gemini-2.5-flash`; sync SDK run via `asyncio.to_thread`).
  - `storage/filesystem.py` — `FilesystemReceiptStorage` (returns a `file://…` `receipt_url`; swap for S3 later = new adapter only).
  - `persistence/` — `models.py` (SQLAlchemy ORM, separate from domain), `database.py` (async engine/session), `repositories.py` (SQLAlchemy repos + `UnitOfWork`, ORM⇄domain mapping).
  - `messaging/telegram_adapter.py` — `TelegramChannel` implementing `MessagingChannel`. **All `python-telegram-bot` lives here.** Handlers only translate update ⇄ `IncomingMessage`; long polling is an internal detail (`run()` is sync and owns its loop).
- `src/app.py` — `BotApplication`: channel-neutral router implementing the `MessageHandler` signature. Coordinates services and emits interactive prompts. This (not the Telegram adapter) holds the photo→confirm→save orchestration.
- `src/main.py` — composition root only. Builds adapters, injects into services + `BotApplication`, wires the handler into the channel, runs. No business logic, no import-time singletons.

### Photo-to-expense flow (the core path)

Telegram update → `TelegramChannel` normalizes to `IncomingMessage` (media bytes downloaded by the adapter) → `BotApplication.handle` → `OrgService.resolve_context` → `ExpenseService.create_draft_from_image` (Gemini extract + receipt stored + draft `PENDING_REVIEW`) → `BotApplication` emits an `InteractivePrompt` (Confirmar/Cancelar) → user taps → adapter sends an `IncomingMessage` with `action="exp_ok:<id>"`/`"exp_no:<id>"` → `ExpenseService.confirm`/`cancel`.

Any change to the extracted-field set must stay consistent across: the Gemini prompt keys (`ai_engine.py`), `ExtractedExpense` (`ports/ai.py`), `Expense` (`entities.py`), the ORM model (`persistence/models.py`) + a new Alembic migration, and the confirmation formatting (`app.py`).

## Notes & gotchas

- **`alembic/env.py` runs async** through asyncpg and pulls the URL + metadata from `src.config`/the ORM models — there is no separate sync DB driver and no URL in `alembic.ini`.
- The interactive prompt is intentionally abstract: action keys are echoed back verbatim in `IncomingMessage.action`, so the flow is **stateless** (no in-memory session). The draft prompt offers `exp_ok`/`exp_no`/`exp_cat`/`exp_cc:<id>`; the category/cost-center pickers echo `setcat`/`setcc:<id>:<idx>` where `<idx>` indexes into the org's (deterministically ordered) category/cost-center list. A WhatsApp adapter would map the same keys to its own button primitives.
- **Active org**: a user can belong to many orgs (auto-created personal org + joined companies). `User.active_org_id` decides where expenses land; `/criar_empresa` and `/entrar` switch it, `/trocar` changes it, `/empresa` shows it. `resolve_context` returns the active org, falling back to the oldest membership if unset.
- **Bot commands** live only as routing in `app.py._handle_text` (a command→handler dict): `/start`, `/gasto`, `/listar`, `/resumo`, `/criar_empresa`, `/entrar`, `/empresa`, `/empresas`, `/trocar`, `/categorias`, `/add_categoria`, `/centros`, `/add_centro`. The Telegram adapter just forwards text; it has no command knowledge.
- `src/adapters/spreadsheet.py` (Google Sheets) is **not wired** and predates Fase 0 — treat as legacy/unused.
- `google-generativeai` is deprecated upstream (warns on import); a future task may migrate to `google-genai`. Out of Fase 0 scope.
- The `Expense.date` (domain `date`) vs ORM `date_at` column split is deliberate; `ExtractedExpense.date` is the only string form, parsed in `ExpenseService`.
