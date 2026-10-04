"""LLM provider selection, driven by LLM_PROVIDER / LLM_MODEL."""

from app.ai.providers.base import LLMError, LLMProvider, TextDelta, ToolCall, TurnResult
from app.config import GEMINI_OPENAI_BASE_URL, Settings

__all__ = [
    "LLMError",
    "LLMProvider",
    "ModelNotAllowed",
    "ProviderNotConfigured",
    "TextDelta",
    "ToolCall",
    "TurnResult",
    "make_provider",
]


class ProviderNotConfigured(RuntimeError):
    pass


class ModelNotAllowed(ValueError):
    pass


def make_provider(settings: Settings, model: str | None = None) -> LLMProvider:
    """The configured provider, for `model` (default: the configured model).

    `model` usually comes from the browser, so it must be on the allowlist.
    """
    if model and model not in settings.allowed_llm_models:
        raise ModelNotAllowed(
            f"Model {model!r} is not available. Choose one of: {', '.join(settings.allowed_llm_models)}"
        )
    model = model or settings.resolved_llm_model
    if settings.llm_provider == "gemini":
        if not settings.gemini_api_key:
            raise ProviderNotConfigured("GEMINI_API_KEY is not set")
        from app.ai.providers.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(
            name="gemini", model=model, api_key=settings.gemini_api_key, base_url=GEMINI_OPENAI_BASE_URL
        )
    if settings.llm_provider == "openai_compatible":
        if not (settings.llm_api_key and settings.llm_base_url and model):
            raise ProviderNotConfigured("LLM_API_KEY, LLM_BASE_URL and LLM_MODEL must be set")
        from app.ai.providers.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(
            name="openai_compatible", model=model, api_key=settings.llm_api_key, base_url=settings.llm_base_url
        )
    if not settings.anthropic_api_key:
        raise ProviderNotConfigured("ANTHROPIC_API_KEY is not set")
    from app.ai.providers.anthropic import AnthropicProvider

    return AnthropicProvider(model=model, api_key=settings.anthropic_api_key, effort=settings.llm_effort)
