import google.generativeai as genai
import json



class AIEngine:
    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        
        self.model = genai.GenerativeModel(model_name='gemini-2.5-flash') 
        
    def extract_expense_from_image(self, image_bytes):
        prompt = """
        Analise a imagem deste comprovante fiscal e extraia os dados.
        Responda APENAS com um objeto JSON:
        {
            "store_name": "string",
            "total_amount": float,
            "category": "string",
            "date": "DD/MM/YYYY",
            "payment_method": "string"
        }
        """
        
        
        try:
            image_part = {
                "mime_type": "image/jpeg",
                "data": bytes(image_bytes)
            }
            response = self.model.generate_content([prompt, image_part])
            
            
            text_data = response.text.replace('```json', '').replace('```', '').strip()
            return json.loads(text_data)
        except Exception as e:
            print(f"Erro detalhado na API Gemini: {e}")
            raise e