import logging
import os
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

_MAX_TOKENS_OUT = 1024
_TEMPERATURE = 0.2


class LLMProvider(ABC):
    """
    Abstract base class for LLM provider implementations.

    Defines the interface for pluggable LLM backends (OpenAI, Gemini, Ollama).
    Each implementation encapsulates API client initialization, authentication,
    and response generation with consistent hyperparameters.
    """

    @abstractmethod
    def ask(self, context: str, question: str, template: str) -> str:
        """
        Generate a synthesis response given context, question, and prompt template.

        Args:
            context (str): Structured context from the RAG pipeline (up to 16,000 characters).
            question (str): Original question from the educational manager.
            template (str): Granularity-specific prompt template with placeholders.

        Returns:
            str: Synthesized response from the LLM (up to 1024 tokens).
        """
        ...


class OpenAIProvider(LLMProvider):
    """
    OpenAI GPT provider with default gpt-4o-mini configuration.

    This provider offers the best cost-to-performance ratio for Portuguese text
    synthesis. Uses OpenAI Chat Completions API with streaming-compatible output.
    """

    def __init__(self) -> None:
        """
        Initialize OpenAI client with API key and model selection from environment.

        Sets up the OpenAI client with credentials from `OPENAI_API_KEY` environment
        variable. Falls back to `gpt-4o-mini` if `OPENAI_MODEL` is not specified.

        Raises:
            openai.AuthenticationError: If API key is invalid or missing.
        """
        from openai import OpenAI

        self._client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
        self._model_name = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    def ask(self, context: str, question: str, template: str) -> str:
        """
        Generate synthesis response using OpenAI Chat Completions API.

        Formats the prompt by substituting context and question into the template,
        then invokes the API with deterministic settings (temperature 0.2, max 1024 tokens).

        Args:
            context (str): Structured context from RAG pipeline.
            question (str): Educational manager's question.
            template (str): Granularity-specific prompt template.

        Returns:
            str: LLM-generated response up to 1024 tokens.

        Raises:
            openai.APIError: On API communication failure.
            openai.APIConnectionError: On network error.
        """
        prompt = template.format(context=context, question=question)
        response = self._client.chat.completions.create(
            model=self._model_name,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=_MAX_TOKENS_OUT,
            temperature=_TEMPERATURE,
        )
        return response.choices[0].message.content


class GeminiProvider(LLMProvider):
    """
    Google Gemini Flash provider with free-tier quotas.

    This provider uses Gemini 1.5 Flash, suitable for cost-free initial deployments
    with adequate performance for Portuguese educational text analysis.
    """

    def __init__(self) -> None:
        """
        Initialize Gemini client with API key from environment.

        Sets up the Google Generative AI client with credentials from `GEMINI_API_KEY`.
        Falls back to `gemini-1.5-flash` if `GEMINI_MODEL` is not specified.

        Raises:
            google.auth.exceptions.DefaultCredentialsError: If API key is missing.
        """
        import google.generativeai as genai

        genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))
        self._model = genai.GenerativeModel(
            os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
        )

    def ask(self, context: str, question: str, template: str) -> str:
        """
        Generate synthesis response using Google Generative AI API.

        Formats the prompt and invokes Gemini with deterministic settings (temperature 0.2,
        max 1024 output tokens).

        Args:
            context (str): Structured context from RAG pipeline.
            question (str): Educational manager's question.
            template (str): Granularity-specific prompt template.

        Returns:
            str: LLM-generated response up to 1024 tokens.

        Raises:
            google.api_core.exceptions.GoogleAPICallError: On API communication failure.
        """
        prompt = template.format(context=context, question=question)
        response = self._model.generate_content(
            prompt,
            generation_config={
                "max_output_tokens": _MAX_TOKENS_OUT,
                "temperature": _TEMPERATURE,
            },
        )
        return response.text


class OllamaProvider(LLMProvider):
    """
    Ollama local LLM provider with zero API cost.

    This provider runs open-source models (e.g., Llama 3.2) locally via Ollama,
    suitable for on-premises or air-gapped deployments. Requires adequate CPU/GPU
    resources for acceptable latency.
    """

    def __init__(self) -> None:
        """
        Initialize Ollama client pointing to local model server.

        Connects to an Ollama server instance at the URL specified by `OLLAMA_BASE_URL`
        environment variable (defaults to `http://localhost:11434`). Falls back to
        `llama3.2` if `OLLAMA_MODEL` is not specified.

        Raises:
            ConnectionError: If unable to reach Ollama server.
        """
        import ollama

        self._client = ollama.Client(
            host=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        )
        self._model_name = os.environ.get("OLLAMA_MODEL", "llama3.2")

    def ask(self, context: str, question: str, template: str) -> str:
        """
        Generate synthesis response using Ollama generate endpoint.

        Formats the prompt and invokes the local model with deterministic settings
        (temperature 0.2, max 1024 output tokens).

        Args:
            context (str): Structured context from RAG pipeline.
            question (str): Educational manager's question.
            template (str): Granularity-specific prompt template.

        Returns:
            str: LLM-generated response up to 1024 tokens.

        Raises:
            ConnectionError: If unable to reach Ollama server.
            RuntimeError: If local model inference fails.
        """
        prompt = template.format(context=context, question=question)
        response = self._client.generate(
            model=self._model_name,
            prompt=prompt,
            options={"num_predict": _MAX_TOKENS_OUT, "temperature": _TEMPERATURE},
        )
        return response["response"]


def get_llm_client() -> LLMProvider:
    """
    Factory function to instantiate the configured LLM provider at runtime.

    Reads the `LLM_PROVIDER` environment variable (case-insensitive) and returns
    an instance of the appropriate provider class (OpenAI, Gemini, or Ollama).
    Logs provider selection and model name for debugging. Fails fast with a clear
    error message if the configuration is invalid.

    **Note:** Do not confuse this with the embedding model (sentence-transformers).
    The embedding model is always local (loaded in `student_embedder.get_model()`)
    and never passes through this factory. This factory is exclusive to the LLM
    synthesis backend for generating responses to educational managers.

    Args:
        None

    Returns:
        LLMProvider: Instance of OpenAIProvider, GeminiProvider, or OllamaProvider
            based on `LLM_PROVIDER` environment variable.

    Raises:
        ValueError: If `LLM_PROVIDER` is not one of 'openai', 'gemini', or 'ollama'.

    Examples:
        >>> llm = get_llm_client()  # Uses OpenAI by default
        >>> response = llm.ask(context, question, template)
    """
    provider = os.environ.get("LLM_PROVIDER", "openai").lower()
    if provider == "openai":
        logger.info(
            "LLM provider: OpenAI (%s)", os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        )
        return OpenAIProvider()
    elif provider == "gemini":
        logger.info("LLM provider: Gemini Flash")
        return GeminiProvider()
    elif provider == "ollama":
        logger.info(
            "LLM provider: Ollama (%s)", os.environ.get("OLLAMA_MODEL", "llama3.2")
        )
        return OllamaProvider()
    raise ValueError(
        f"Invalid LLM_PROVIDER: '{provider}'. Use 'openai', 'gemini', or 'ollama'."
    )
