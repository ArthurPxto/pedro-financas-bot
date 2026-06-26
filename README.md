# 💰 Pedro Finanças - AI-Powered Expense Tracker Bot

A multi-tenant expense bot. By leveraging **Multimodal AI (Gemini 2.5 Flash)**, it extracts financial data from receipts, invoices, or banking screenshots, lets the user **confirm before saving**, and stores each expense per organization/user in **PostgreSQL** — keeping the receipt image for audit. The messaging channel (Telegram today) sits behind a port, so adding WhatsApp later is a new adapter, not a rewrite.

---

## 🚀 Features

* **Intelligent OCR & Context:** Uses Google Gemini to understand not just the text, but the context of the receipt (Store, Amount, Date, Category) directly from images.
* **Multi-Tenant:** Expenses scoped per organization/user in PostgreSQL; identity decoupled from the channel (`ChannelIdentity`), so one user can have Telegram + WhatsApp.
* **Review before save:** AI extraction becomes a draft the user confirms (or cancels) via an interactive prompt; receipts are kept for audit.
* **Dynamic Reports:** `/resumo` (monthly spending) and `/listar` (last 5 expenses).
* **Hexagonal Architecture:** Ports & adapters — the core knows nothing about Telegram; new channels are new adapters.

---

## 🏗️ Architecture

The project follows **ports & adapters (hexagonal)**: the business core depends only on its own ports, adapters implement them, and the composition root (`main.py`) wires everything. The core never imports an adapter — adding a channel (WhatsApp) or swapping storage (S3) does not touch `core/`.



### Project Structure (ports & adapters):
```text
├── src/
│   ├── core/
│   │   ├── entities.py     # Pure domain models (Org, User, ChannelIdentity, Expense…)
│   │   ├── ports/          # Interfaces the core needs (messaging, repos, ai, storage)
│   │   └── services/       # Channel-neutral business logic (OrgService, ExpenseService)
│   ├── adapters/
│   │   ├── ai_engine.py    # Gemini extractor
│   │   ├── persistence/    # SQLAlchemy models + repositories + async engine
│   │   ├── storage/        # Receipt storage (filesystem; S3 later)
│   │   ├── messaging/      # Telegram adapter (all python-telegram-bot lives here)
│   │   ├── security/       # JwtTokenIssuer (TokenIssuer via PyJWT)
│   │   └── web/            # FastAPI API do painel (driving adapter)
│   ├── app.py              # Channel-neutral router (BotApplication)
│   ├── config.py           # Boot-time config (pydantic-settings)
│   ├── main.py             # Composition root do bot
│   └── api.py              # Composition root da API web (uvicorn)
├── web/                    # Painel SPA (React + Vite + TS) — consome src/api.py
├── alembic/                # Migrations (async, asyncpg)
├── docker-compose.yml      # Local PostgreSQL
└── requirements.txt
```

## 🛠️ Tech Stack

- Language: Python 3.14
- AI Engine: Google Generative AI (Gemini 2.5 Flash)
- Data Validation & Config: Pydantic / pydantic-settings
- Telegram Framework: python-telegram-bot (async)
- Database: PostgreSQL + SQLAlchemy (async / asyncpg) + Alembic
- Logging: structlog

## 🚀 Features

- Intelligent OCR: Uses Google Gemini to understand context (Store, Amount, Date, Category) directly from images.

- Multi-Tenant: Org/User domain model; expenses reference an internal user_id, never a raw Telegram ID.

- Financial Reports: 
    * /resumo: Monthly spending summary.
    * /listar: View the last 5 recorded transactions.

- UX/UI: Formatted Markdown responses and helpful /start guidance.

## ⚙️ How to Run

 ### 1. Prerequisites
    - Python 3.14, `uv`, and Docker (for local PostgreSQL).

    - A Telegram Bot Token (obtained from @BotFather).

    - A Google AI Studio API Key (Gemini API).

### 2. Installation
Clone the repository and install the required packages:

```bash
git clone https://github.com/your-username/pedro-financas-bot.git
cd pedro-financas-bot
uv venv --python 3.14 .venv
uv pip install -r requirements.txt --python .venv
```

### 3. Configuration
Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
# edit TELEGRAM_TOKEN and GEMINI_API_KEY
```

### 4. Database
Start PostgreSQL and apply migrations:
```bash
docker compose up -d
.venv/bin/alembic upgrade head
```

### 5. Running the application
```bash
# Bot do Telegram
.venv/bin/python -m src.main

# API do painel web (Fase 3 — processo separado, mesmo banco; requer WEB_JWT_SECRET)
.venv/bin/python -m src.api    # http://localhost:8000  (/docs para o Swagger)

# Painel web (SPA React/Vite) — consome a API acima
cd web && npm install && npm run dev   # http://localhost:5173

# Dados de exemplo + link de acesso pronto (com API e SPA no ar)
.venv/bin/python -m scripts.seed_demo  # cria a empresa "ACME Demo" e imprime o magic-link
```

> Acesso ao painel: envie `/login` ao bot no Telegram → ele manda um link
> (`http://localhost:5173/login?token=…`) → abra no navegador. O painel é a
> visão do **gestor** (admin/owner); o funcionário continua no bot.
## 📝 User Commands

**Gastos**
- `/start` — welcome message + command list.
- _(enviar foto de comprovante)_ — extração via IA → revisão (confirmar / editar categoria / editar centro de custo / excluir).
- `/gasto <valor> <descrição>` — lança um gasto por texto (ex.: `/gasto 50 mercado almoço`).
- `/listar` — últimos gastos registrados. `/resumo [meses]` — total do período.

**Equipe (Fase 1)**
- `/criar_empresa <nome>` — cria uma empresa; você vira admin e recebe um código de convite.
- `/entrar <código>` — entra numa empresa pelo código (como membro).
- `/empresa` — empresa ativa + papel (e código, se admin). `/empresas`, `/trocar <id>` — alternar org ativa.

**Categorias e centros de custo (admin)**
- `/add_categoria <nome>`, `/categorias` — categorias da org (a IA sugere dentro delas).
- `/add_centro <nome>`, `/centros` — centros de custo da org.

**Reembolso / aprovação (Fase 2)**
- Ao confirmar, o gasto de um **membro** vai para aprovação (`aguardando → aprovado/rejeitado → reembolsado`); quem é **admin/owner** aprova direto (uso pessoal segue sem fricção).
- `/reembolsos` — funcionário acompanha o status dos seus gastos enviados.
- `/aprovacoes` — aprovador vê a fila com botões Aprovar/Rejeitar e "Aprovar todos" (aprovação em lote).
- `/aprovar <id>`, `/aprovar_todos`, `/reembolsar <id>` — ações do aprovador.
- `/rejeitar <id> <motivo>` — rejeita com **comentário obrigatório**.
- Aprovadores recebem **notificação push** quando há gastos na fila; o autor é avisado da decisão.

**Painel web (Fase 3 — backend)**
- `/login` no bot envia um **magic-link** de acesso (auth pelo canal já linkado; reusa `ChannelIdentity` + o push da Fase 2).
- API FastAPI (`src.api`), processo separado sobre os **mesmos serviços**: `POST /auth/exchange`, `GET /auth/me`, `GET /reports/overview` (totais por categoria/centro/pessoa/mês), `GET /reports/export.csv`.
- Relatórios são **só para admin/owner** (visão do gestor); JSON + CORS.
- **Painel SPA (`web/`, React/Vite):** login pelo magic-link do bot; herói com o total do período + filtros (de/até/status), rankings por categoria/centro/pessoa/mês e exportação CSV. _Aprovações pela web e export Sheets/PDF ficam para o próximo passo._

## 🤝 Contributing
Contributions, issues, and feature requests are welcome! Feel free to check the issues page.