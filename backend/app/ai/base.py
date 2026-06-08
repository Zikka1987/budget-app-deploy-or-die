from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID


@dataclass
class ParsedLineItem:
    description: str
    total_price: Decimal
    quantity: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None
    line_number: Optional[int] = None
    confidence: Optional[float] = None


@dataclass
class ParsedReceipt:
    store_name: Optional[str] = None
    receipt_date: Optional[date] = None
    total_amount: Optional[Decimal] = None
    items: list[ParsedLineItem] = field(default_factory=list)
    raw_text: Optional[str] = None
    confidence: Optional[float] = None


@dataclass
class ItemToCategorize:
    """An already-persisted receipt_item being offered to the categorizer.

    Has a DB id so the AI can refer back to specific rows in its output.
    """
    id: UUID
    description: str
    total_price: Decimal


@dataclass
class CategorySuggestion:
    """AI output for a single item.

    suggested_category_id may be None if the AI is unsure — Python treats
    that as "no suggestion, item needs review." Python owns the
    requires_review decision (see receipt_rules.determine_requires_review),
    so it is intentionally absent from this dataclass.
    """
    receipt_item_id: UUID
    suggested_category_id: Optional[UUID]
    confidence: Optional[float]


@dataclass
class CategorizationResult:
    suggestions: list[CategorySuggestion] = field(default_factory=list)


class ReceiptParserBase(ABC):
    """Abstract interface for receipt image parsing."""

    @abstractmethod
    async def parse(self, image_bytes: bytes, mime_type: str) -> ParsedReceipt:
        """Parse a receipt image and extract structured data."""
        ...


class CategorizerBase(ABC):
    """Abstract interface for receipt item categorization."""

    @dataclass
    class CategoryOption:
        id: UUID
        name: str
        type: str

    @abstractmethod
    async def categorize(
        self,
        items: list[ItemToCategorize],
        categories: list[CategoryOption],
    ) -> CategorizationResult:
        """Suggest a category for each receipt item.

        Input items are already-persisted receipt_items (they carry DB ids
        the AI can refer back to). Input categories are the active expense
        categories for the household.

        The returned CategorizationResult may contain fewer suggestions
        than input items — it is the AI's prerogative to return "no
        suggestion" for an item by omitting it or returning None for
        suggested_category_id. Python validates and decides
        requires_review downstream.
        """
        ...
