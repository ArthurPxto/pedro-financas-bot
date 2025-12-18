# 💰 Pedro Finanças - AI-Powered Expense Tracker Bot

A professional Telegram bot designed to simplify personal finance management for the everyday user. By leveraging **Multimodal AI (Gemini 2.5 Flash)**, the bot automatically extracts financial data from receipts, invoices, or banking screenshots and organizes them into a structured SQLite database.

---

## 🚀 Features

* **Intelligent OCR & Context:** Uses Google Gemini to understand not just the text, but the context of the receipt (Store, Amount, Date, Category) directly from images.
* **Multi-User Support:** Built-in SQLite database to manage expenses per Telegram user ID.
* **Dynamic Reports:** * `/resumo`: Get a summary of the current month's spending.
    * `/listar`: View a formatted list of the last 5 recorded expenses.
* **Clean Architecture:** Decoupled code logic (Entities, Adapters, Core) for easy maintenance and scalability.

---

## 🏗️ Architecture & Clean Code

The project follows **Clean Architecture** principles to ensure that the business logic remains independent of external frameworks like the Telegram API or Google Cloud.



### Project Structure:
```text
├── src/
│   ├── core/           # Business Rules (Entities & Pydantic Models)
│   ├── adapters/       # Interfaces (Gemini AI, SQLite Database, Telegram)
│   └── main.py         # Application Entry Point & Orchestration
├── .env                # API Keys (Not versioned)
├── requirements.txt    # Project Dependencies
└── README.md           # Documentation
``` 

## 🛠️ Tech Stack

- Language: Python 3.10+
- AI Engine: Google Generative AI (Gemini 2.5 Flash)
- Data Validation: Pydantic (Strong typing for financial data)
- Telegram Framework: python-telegram-bot (Async version)
- Database: SQLite (Relational storage for multi-user support)

## 🚀 Features

- Intelligent OCR: Uses Google Gemini to understand context (Store, Amount, Date, Category) directly from images.

- Multi-User Support: Database schema designed to associate expenses with specific Telegram User IDs.

- Financial Reports: 
    * /resumo: Monthly spending summary.
    * /listar: View the last 5 recorded transactions.

- UX/UI: Formatted Markdown responses and helpful /start guidance.

## ⚙️ How to Run

 ### 1. Prerequisites
    - Python 3.10 or higher installed.

    - A Telegram Bot Token (obtained from @BotFather).

    - A Google AI Studio API Key (Gemini API).

### 2. Installation 
Clone the repository and install the required packages:

```bash
    git clone [https://github.com/your-username/pedro-financas-bot.git](https:/github.com/your-username/pedro-financas-bot.git)
cd pedro-financas-bot
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configuration
Create a .env file in the root directory with your credentials:
```text
TELEGRAM_TOKEN=your_telegram_bot_token_here
GEMINI_API_KEY=your_google_gemini_key_here
```
### 4. Running the application
```bash
python -m src.main
```
## 📝 User Commands
    /start - Displays the welcome message and all bot functionalities.

    /resumo - Shows total expenses for the last 30 days.

    /resumo [number] - Shows total expenses for the specified number of months (e.g., /resumo 3).

    /listar - Lists the 5 most recent transactions registered in the database.

## 🤝 Contributing
Contributions, issues, and feature requests are welcome! Feel free to check the issues page.