import os
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters , CommandHandler
from src.adapters.ai_engine import AIEngine
from src.adapters.database import DatabaseAdapter
from src.core.entities import Expense

load_dotenv()


ai_engine = AIEngine(api_key=os.getenv("GEMINI_API_KEY"))
db_adapter = DatabaseAdapter()

async def listar(update, context):
    user_id = update.effective_user.id
    gastos = db_adapter.get_recent_expenses(user_id)
    
    if not gastos:
        await update.message.reply_text("Nenhum gasto encontrado.")
        return

    resposta = "📋 *Últimos gastos registrados:*\n\n"
    for gasto in gastos:
        data = gasto[0]
        loja = gasto[1]
        valor = gasto[2]
        resposta += f"📅 {data} - *{loja}*: R$ {valor:.2f}\n"
    
    await update.message.reply_text(resposta, parse_mode='Markdown')

async def resumo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    months = 1
    if context.args:
        try:
            months = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Por favor, use um número para os meses. Ex: /resumo 3")
            return

    total = db_adapter.get_summary(user_id, months)
    
    await update.message.reply_text(
        f"📊 *Resumo Financeiro*\n"
        f"Período: Último(s) {months} mês(es)\n"
        f"💰 *Total acumulado: R$ {total:.2f}*",
        parse_mode='Markdown'
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    message = (
        f"Olá, *{user_name}*! 👋 Bem-vindo ao seu Assistente Financeiro Pessoal.\n\n"
        "Eu utilizo Inteligência Artificial para ajudar você a controlar seus gastos de forma simples.\n\n"
        "✨ *O que eu posso fazer por você:*\n"
        "📸 *Processar Recibos:* Envie uma foto de um comprovante, nota fiscal ou print de banco. Eu extrairei automaticamente o valor, a loja, a data e a categoria.\n"
        "📊 *Resumos Financeiros:* Use comandos para saber quanto você já gastou.\n"
        "📅 *Organização:* Salvo tudo em um banco de dados privado associado à sua conta.\n\n"
        "🚀 *Comandos disponíveis:*\n"
        "[/listar](https://t.me/) - Lista os ultimos 5 gastos recentes.\n"
        "[/resumo](https://t.me/) - Total de gastos do último mês.\n"
        "[/resumo 3](https://t.me/) - Total de gastos dos últimos 3 meses.\n"
        "[/start](https://t.me/) - Lista estas funcionalidades novamente.\n\n"
        "_Experimente enviar uma foto de um comprovante agora!_"
    )
    await update.message.reply_text(message, parse_mode='Markdown')

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    
    user_id = update.effective_user.id
    
    # 1. Feedback visual para o usuário
    await update.message.reply_text("Recebi a foto! Processando os dados com IA... 🤖")
    
    # 2. Baixa a foto do Telegram
    photo_file = await update.message.photo[-1].get_file()
    image_bytes = await photo_file.download_as_bytearray()
    
    try:
        # 3. Extração via Gemini
        extracted_data = ai_engine.extract_expense_from_image(image_bytes)
        
        extracted_data["user_id"] = user_id
        
        expense = Expense(**extracted_data) # Validação Pydantic
        
        # 4. Salva na Base de dados
        success = db_adapter.save_expense(expense)
        
        if success:
            msg = (f"✅ Gasto registrado!\n"
                   f"📍 {expense.store_name}\n"
                   f"💰 R$ {expense.total_amount:.2f}\n"
                   f"📂 {expense.category}\n"
                   f"📅 Data: {expense.date}\n")
            await update.message.reply_text(msg)
        else:
            await update.message.reply_text("❌ Erro ao salvar no banco de dados.")
            
    except Exception as e:
        await update.message.reply_text(f"⚠️ Não consegui ler o comprovante: {e}")

if __name__ == '__main__':
    
    token = os.getenv("TELEGRAM_TOKEN")
    application = ApplicationBuilder().token(token).build()
    
    #  Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(CommandHandler("resumo", resumo))
    application.add_handler(CommandHandler("listar", listar))
    
    print("Bot rodando... Pressione Ctrl+C para parar.")
    application.run_polling()