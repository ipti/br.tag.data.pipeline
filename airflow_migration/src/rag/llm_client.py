import logging
import os
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

_MAX_TOKENS_OUT  = 1024
_TEMPERATURE     = 0.2


class LLMProvider(ABC):
    @abstractmethod
    def ask(self, context: str, question: str, template: str) -> str: ...


class OpenAIProvider(LLMProvider):
    """OpenAI GPT — provider padrão. Melhor custo/benefício para português."""

    def __init__(self) -> None:
        from openai import OpenAI
        self._client     = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
        self._model_name = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    def ask(self, context: str, question: str, template: str) -> str:
        prompt = template.format(context=context, question=question)
        response = self._client.chat.completions.create(
            model=self._model_name,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=_MAX_TOKENS_OUT,
            temperature=_TEMPERATURE,
        )
        return response.choices[0].message.content


class GeminiProvider(LLMProvider):
    """Google Gemini Flash — free tier suficiente para uso inicial."""

    def __init__(self) -> None:
        import google.generativeai as genai
        genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))
        self._model = genai.GenerativeModel(os.environ.get("GEMINI_MODEL", "gemini-1.5-flash"))

    def ask(self, context: str, question: str, template: str) -> str:
        prompt = template.format(context=context, question=question)
        response = self._model.generate_content(
            prompt,
            generation_config={"max_output_tokens": _MAX_TOKENS_OUT, "temperature": _TEMPERATURE},
        )
        return response.text


class OllamaProvider(LLMProvider):
    """Ollama local — sem custo de API, requer CPU/GPU adequada."""

    def __init__(self) -> None:
        import ollama
        self._client     = ollama.Client(host=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"))
        self._model_name = os.environ.get("OLLAMA_MODEL", "llama3.2")

    def ask(self, context: str, question: str, template: str) -> str:
        prompt = template.format(context=context, question=question)
        response = self._client.generate(
            model=self._model_name,
            prompt=prompt,
            options={"num_predict": _MAX_TOKENS_OUT, "temperature": _TEMPERATURE},
        )
        return response["response"]


def get_llm_client() -> LLMProvider:
    """
    Factory — lê LLM_PROVIDER do ambiente. Falha rápido se mal configurado.

    Não confundir com o modelo de embedding: sentence-transformers é sempre
    local (get_model() em student_embedder.py) e nunca passa por aqui.
    Este factory é exclusivo para o LLM de síntese/resposta ao gestor.
    """
    provider = os.environ.get("LLM_PROVIDER", "openai").lower()
    if provider == "openai":
        logger.info("LLM provider: OpenAI (%s)", os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
        return OpenAIProvider()
    elif provider == "gemini":
        logger.info("LLM provider: Gemini Flash")
        return GeminiProvider()
    elif provider == "ollama":
        logger.info("LLM provider: Ollama (%s)", os.environ.get("OLLAMA_MODEL", "llama3.2"))
        return OllamaProvider()
    raise ValueError(f"LLM_PROVIDER inválido: '{provider}'. Use 'openai', 'gemini' ou 'ollama'.")
