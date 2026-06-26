"""Adapter de IA: Google Gemini implementando o port `ExpenseExtractor`."""
import asyncio
import json
from typing import Optional

import google.generativeai as genai

from src.core.ports.ai import ExpenseExtractor, ExtractedExpense
from src.logging_config import get_logger

log = get_logger(__name__)

_BASE_PROMPT = """
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

_CATEGORY_HINT = (
    "\nPara o campo \"category\", escolha OBRIGATORIAMENTE uma destas categorias "
    "da empresa (use exatamente o texto): {categories}. "
    "Se nenhuma se encaixar, use a mais próxima.\n"
)


class GeminiExpenseExtractor(ExpenseExtractor):
    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash"):
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(model_name=model_name)

    async def extract(
        self,
        image: bytes,
        mime_type: str = "image/jpeg",
        categories: Optional[list[str]] = None,
    ) -> ExtractedExpense:
        prompt = _BASE_PROMPT
        if categories:
            prompt += _CATEGORY_HINT.format(categories=", ".join(categories))
        # O SDK do Gemini é síncrono; roda fora do event loop para não bloqueá-lo.
        raw = await asyncio.to_thread(self._generate, prompt, image, mime_type)
        return ExtractedExpense(**raw)

    def _generate(self, prompt: str, image: bytes, mime_type: str) -> dict:
        try:
            image_part = {"mime_type": mime_type, "data": bytes(image)}
            response = self._model.generate_content([prompt, image_part])
            text = response.text.replace("```json", "").replace("```", "").strip()
            return json.loads(text)
        except Exception:
            log.exception("falha na extração via Gemini")
            raise
