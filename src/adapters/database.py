import sqlite3
from datetime import datetime, timedelta

class DatabaseAdapter:
    def __init__(self, db_path="finance_bot.db"):
        self.db_path = db_path
        self._create_table()

    def _create_table(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    store_name TEXT,
                    total_amount REAL,
                    category TEXT,
                    date_at DATE,
                    payment_method TEXT
                )
            """)

    def save_expense(self, expense):
        try:
            date_obj = datetime.strptime(expense.date, "%d/%m/%Y").date()
        
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO expenses (user_id, store_name, total_amount, category, date_at, payment_method)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (expense.user_id, expense.store_name, expense.total_amount, 
                    expense.category, date_obj, expense.payment_method))
                return True
        except Exception as e:
            print(f"Erro ao salvar no banco de dados: {e}")
        return False
        
    def get_summary(self, user_id, months=1):
        start_date = datetime.now() - timedelta(days=30 * months)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT SUM(total_amount) FROM expenses 
                WHERE user_id = ? AND date_at >= ?
            """, (user_id, start_date.date()))
            return cursor.fetchone()[0] or 0.0
        
    def get_recent_expenses(self, user_id: int, limit: int = 5):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT date_at, store_name, total_amount 
                FROM expenses 
                WHERE user_id = ? 
                ORDER BY id DESC 
                LIMIT ?
            """, (user_id, limit))
            return cursor.fetchall()