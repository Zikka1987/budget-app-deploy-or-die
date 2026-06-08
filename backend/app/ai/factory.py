"""Factory for AI provider selection.

Services import `get_receipt_parser` / `get_categorizer` (not the concrete
classes) so provider selection stays behind the abstraction and can be
overridden in tests via monkeypatch.
"""

from app.ai.base import CategorizerBase, ReceiptParserBase
from app.core.config import settings


def get_receipt_parser() -> ReceiptParserBase:
    """Return the configured receipt parser instance.

    Provider is selected by the OCR_PROVIDER config variable. Raises
    ValueError if the configured provider is not recognized.
    """
    provider = (settings.ocr_provider or "").lower()
    if provider == "anthropic":
        from app.ai.receipt_parser import AnthropicReceiptParser

        return AnthropicReceiptParser(
            api_key=settings.anthropic_api_key,
            model=settings.ocr_model,
            max_tokens=settings.ocr_max_tokens,
        )
    raise ValueError(f"Unknown OCR_PROVIDER: {settings.ocr_provider}")


def get_categorizer() -> CategorizerBase:
    """Return the configured receipt categorizer instance.

    Provider is selected by the OCR_PROVIDER config variable (shared with
    the parser — same provider handles both OCR and categorization).
    """
    provider = (settings.ocr_provider or "").lower()
    if provider == "anthropic":
        from app.ai.categorizer import AnthropicCategorizer

        return AnthropicCategorizer(
            api_key=settings.anthropic_api_key,
            model=settings.ocr_model,
            max_tokens=settings.ocr_max_tokens,
        )
    raise ValueError(f"Unknown OCR_PROVIDER: {settings.ocr_provider}")
