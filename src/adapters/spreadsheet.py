import gspread
from oauth2client.service_account import ServiceAccountCredentials
from src.core.entities import Expense

class SpreadsheetAdapter:
    def __init__(self, credentials_json: str, spreadsheet_id: str):
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_json, scope)
        self.client = gspread.authorize(creds)
        self.sheet = self.client.open_by_key(spreadsheet_id).get_worksheet(0)

    def add_expense(self, expense: Expense):
        try:
            row = [
                expense.date,
                expense.store_name,
                expense.category,
                expense.total_amount,
                expense.payment_method
            ]
            self.sheet.append_row(row)
            return True
        except Exception as e:
            print(f"Erro ao salvar na planilha: {e}")
            return False