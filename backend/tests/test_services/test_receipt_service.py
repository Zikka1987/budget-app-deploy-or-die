"""Mock-based tests for ReceiptService.

These tests patch the Supabase client and the ReceiptRepository class at the
import location used by the service module. They cover the glue logic that
pure-function tests cannot reach: validation error translation, storage /
DB ordering, rollback on DB failure, signed URL attachment, and pagination
forwarding.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.ai.base import (
    CategorizationResult,
    CategorizerBase,
    CategorySuggestion,
    ParsedLineItem,
    ParsedReceipt,
)
from app.core.exceptions import (
    AppError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.services.receipt_service import ReceiptService


HOUSEHOLD_ID = UUID("11111111-1111-1111-1111-111111111111")
USER_ID = UUID("22222222-2222-2222-2222-222222222222")
JPEG_BYTES = b"\xff\xd8\xff\xe0fake jpeg content"


def _make_row(receipt_id: UUID, storage_path: str) -> dict:
    """Build a full receipt row dict matching what the real repo returns."""
    return {
        "id": receipt_id,
        "household_id": HOUSEHOLD_ID,
        "uploaded_by": USER_ID,
        "status": "uploaded",
        "storage_path": storage_path,
        "file_name": "receipt.jpg",
        "mime_type": "image/jpeg",
        "store_name": None,
        "receipt_date": None,
        "total_amount": None,
        "ocr_raw_text": None,
        "ocr_provider": None,
        "ocr_confidence": None,
        "error_message": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


@pytest.fixture
def fake_pool():
    """asyncpg pool fake. acquire() returns an async context manager."""
    pool = MagicMock()
    conn = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=ctx)
    return pool


@pytest.fixture
def fake_supabase(monkeypatch):
    """Replace get_supabase() on the service module with a MagicMock client."""
    client = MagicMock()
    bucket = MagicMock()
    bucket.upload = MagicMock(return_value=MagicMock())
    bucket.remove = MagicMock(return_value=MagicMock())
    bucket.download = MagicMock(return_value=b"fake image bytes")
    bucket.create_signed_url = MagicMock(
        return_value={"signedURL": "https://signed.example/receipts/x"}
    )
    client.storage.from_ = MagicMock(return_value=bucket)
    monkeypatch.setattr(
        "app.services.receipt_service.get_supabase",
        lambda: client,
    )
    return client


@pytest.fixture
def fake_repo(monkeypatch):
    """Replace ReceiptRepository on the service module with a MagicMock.

    The fixture returns the repo instance (the mock that gets constructed
    inside the service), so tests can set return values for its methods.
    """
    repo_instance = MagicMock()
    # Phase 1 upload methods
    repo_instance.create = AsyncMock()
    repo_instance.get_by_id = AsyncMock()
    repo_instance.list_by_household = AsyncMock()
    # Phase 2 parse methods
    repo_instance.mark_processing = AsyncMock()
    repo_instance.mark_failed = AsyncMock()
    repo_instance.update_parse_result = AsyncMock()
    repo_instance.delete_items = AsyncMock()
    repo_instance.insert_items = AsyncMock(return_value=[])
    repo_instance.list_for_duplicate_check = AsyncMock(return_value=[])
    # Phase 3 categorization + review payload methods
    repo_instance.list_items_by_receipt = AsyncMock(return_value=[])
    repo_instance.update_item_suggestions = AsyncMock()
    repo_instance.list_items_with_category_names = AsyncMock(return_value=[])
    repo_class = MagicMock(return_value=repo_instance)
    monkeypatch.setattr(
        "app.services.receipt_service.ReceiptRepository",
        repo_class,
    )
    return repo_instance


@pytest.fixture
def fake_category_repo(monkeypatch):
    """Replace CategoryRepository on the service module with a MagicMock.

    Default: list_by_household returns an empty list. Tests override this.
    """
    repo_instance = MagicMock()
    repo_instance.list_by_household = AsyncMock(return_value=[])
    repo_class = MagicMock(return_value=repo_instance)
    monkeypatch.setattr(
        "app.services.receipt_service.CategoryRepository",
        repo_class,
    )
    return repo_instance


@pytest.fixture
def fake_categorizer(monkeypatch):
    """Replace get_categorizer() on the service module with a mock.

    Default: returns an empty CategorizationResult. Tests override the
    categorize mock to inject specific suggestions.
    """
    categorizer = MagicMock()
    categorizer.categorize = AsyncMock(
        return_value=CategorizationResult(suggestions=[])
    )
    monkeypatch.setattr(
        "app.services.receipt_service.get_categorizer",
        lambda: categorizer,
    )
    return categorizer


@pytest.fixture
def fake_parsed_receipt():
    """A fully populated ParsedReceipt matching what the AI would return."""
    return ParsedReceipt(
        store_name="Netto",
        receipt_date=date(2026, 4, 5),
        total_amount=Decimal("150.00"),
        items=[
            ParsedLineItem(
                description="Maelk",
                total_price=Decimal("12.50"),
                quantity=Decimal("1"),
                unit_price=Decimal("12.50"),
                line_number=1,
                confidence=0.95,
            ),
            ParsedLineItem(
                description="Broed",
                total_price=Decimal("25.00"),
                line_number=2,
                confidence=0.85,
            ),
        ],
        raw_text="Netto\n2026-04-05\nMaelk 12,50\nBroed 25,00\nTotal 150,00",
        confidence=0.9,
    )


@pytest.fixture
def fake_parser(monkeypatch, fake_parsed_receipt):
    """Replace get_receipt_parser() with a mock returning fake_parsed_receipt."""
    parser = MagicMock()
    parser.parse = AsyncMock(return_value=fake_parsed_receipt)
    monkeypatch.setattr(
        "app.services.receipt_service.get_receipt_parser",
        lambda: parser,
    )
    return parser


def _make_parsed_row(receipt_id: UUID) -> dict:
    """A receipt row as it would look AFTER update_parse_result."""
    return {
        "id": receipt_id,
        "household_id": HOUSEHOLD_ID,
        "uploaded_by": USER_ID,
        "status": "ocr_complete",
        "storage_path": f"{HOUSEHOLD_ID}/{receipt_id}/original.jpg",
        "file_name": "receipt.jpg",
        "mime_type": "image/jpeg",
        "store_name": "Netto",
        "receipt_date": date(2026, 4, 5),
        "total_amount": Decimal("150.00"),
        "ocr_raw_text": "Netto\n2026-04-05\nMaelk 12,50\n...",
        "ocr_provider": "anthropic",
        "ocr_confidence": Decimal("0.9"),
        "error_message": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def _make_item_row(receipt_id: UUID, line_number: int, description: str, total: Decimal) -> dict:
    return {
        "id": uuid4(),
        "receipt_id": receipt_id,
        "line_number": line_number,
        "description": description,
        "quantity": None,
        "unit_price": None,
        "total_price": total,
        "suggested_category_id": None,
        "confidence": 0.9,
        "requires_review": True,
        "user_confirmed_category_id": None,
        "is_excluded": False,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


# ── upload_receipt ──


class TestUploadReceipt:
    @pytest.mark.asyncio
    async def test_successful_upload(self, fake_pool, fake_supabase, fake_repo):
        """Validation passes -> storage upload -> DB insert -> returns row."""
        # Arrange: repo.create returns a full row
        captured_receipt_id: list = []

        async def capture_create(**kwargs):
            captured_receipt_id.append(kwargs["receipt_id"])
            return _make_row(kwargs["receipt_id"], kwargs["storage_path"])

        fake_repo.create = AsyncMock(side_effect=capture_create)

        service = ReceiptService(fake_pool)
        result = await service.upload_receipt(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            file_bytes=JPEG_BYTES,
            mime_type="image/jpeg",
            file_name="receipt.jpg",
        )

        # Storage upload was called
        assert fake_supabase.storage.from_.called
        bucket = fake_supabase.storage.from_.return_value
        assert bucket.upload.call_count == 1
        upload_kwargs = bucket.upload.call_args.kwargs
        assert upload_kwargs["file"] == JPEG_BYTES
        assert upload_kwargs["file_options"]["content-type"] == "image/jpeg"
        assert upload_kwargs["file_options"]["upsert"] == "false"  # STRING, not bool

        # Storage path includes the pre-generated receipt_id
        assert len(captured_receipt_id) == 1
        receipt_id = captured_receipt_id[0]
        assert upload_kwargs["path"] == f"{HOUSEHOLD_ID}/{receipt_id}/original.jpg"

        # Repo.create was called with matching receipt_id
        fake_repo.create.assert_called_once()
        create_kwargs = fake_repo.create.call_args.kwargs
        assert create_kwargs["receipt_id"] == receipt_id
        assert create_kwargs["household_id"] == HOUSEHOLD_ID
        assert create_kwargs["uploaded_by"] == USER_ID
        assert create_kwargs["storage_path"] == upload_kwargs["path"]

        # Result contains the full row
        assert result["id"] == receipt_id
        assert result["status"] == "uploaded"
        assert result["items"] == []

    @pytest.mark.asyncio
    async def test_validation_error_no_storage_call(
        self, fake_pool, fake_supabase, fake_repo
    ):
        """Invalid MIME type -> ValidationError -> storage never touched."""
        service = ReceiptService(fake_pool)
        with pytest.raises(ValidationError, match="Unsupported"):
            await service.upload_receipt(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                file_bytes=b"text data",
                mime_type="text/plain",
                file_name="notes.txt",
            )

        bucket = fake_supabase.storage.from_.return_value
        assert bucket.upload.call_count == 0
        assert fake_repo.create.call_count == 0

    @pytest.mark.asyncio
    async def test_empty_file_raises_before_storage(
        self, fake_pool, fake_supabase, fake_repo
    ):
        """Zero-byte file -> ValidationError, no storage call."""
        service = ReceiptService(fake_pool)
        with pytest.raises(ValidationError, match="empty"):
            await service.upload_receipt(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                file_bytes=b"",
                mime_type="image/jpeg",
                file_name="empty.jpg",
            )

        bucket = fake_supabase.storage.from_.return_value
        assert bucket.upload.call_count == 0
        assert fake_repo.create.call_count == 0

    @pytest.mark.asyncio
    async def test_db_insert_failure_triggers_storage_cleanup(
        self, fake_pool, fake_supabase, fake_repo
    ):
        """Storage upload succeeds, DB insert raises -> storage.remove called."""
        fake_repo.create = AsyncMock(side_effect=RuntimeError("DB down"))

        service = ReceiptService(fake_pool)
        with pytest.raises(RuntimeError, match="DB down"):
            await service.upload_receipt(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                file_bytes=JPEG_BYTES,
                mime_type="image/jpeg",
                file_name="receipt.jpg",
            )

        bucket = fake_supabase.storage.from_.return_value
        # Upload happened exactly once
        assert bucket.upload.call_count == 1
        # Cleanup happened exactly once with the same path
        assert bucket.remove.call_count == 1
        uploaded_path = bucket.upload.call_args.kwargs["path"]
        bucket.remove.assert_called_once_with([uploaded_path])

    @pytest.mark.asyncio
    async def test_storage_upload_failure_no_db_insert(
        self, fake_pool, fake_supabase, fake_repo
    ):
        """Storage upload raises -> AppError, repo.create never called."""
        bucket = fake_supabase.storage.from_.return_value
        bucket.upload = MagicMock(side_effect=RuntimeError("S3 unreachable"))

        service = ReceiptService(fake_pool)
        with pytest.raises(AppError, match="Storage upload failed"):
            await service.upload_receipt(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                file_bytes=JPEG_BYTES,
                mime_type="image/jpeg",
                file_name="receipt.jpg",
            )

        assert fake_repo.create.call_count == 0
        # No cleanup because nothing was uploaded
        assert bucket.remove.call_count == 0

    @pytest.mark.asyncio
    async def test_household_id_in_storage_path(
        self, fake_pool, fake_supabase, fake_repo
    ):
        """Storage path must start with household_id and end with /original.jpg."""
        fake_repo.create = AsyncMock(
            side_effect=lambda **kwargs: _make_row(
                kwargs["receipt_id"], kwargs["storage_path"]
            )
        )

        service = ReceiptService(fake_pool)
        await service.upload_receipt(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            file_bytes=JPEG_BYTES,
            mime_type="image/jpeg",
            file_name="r.jpg",
        )

        bucket = fake_supabase.storage.from_.return_value
        path = bucket.upload.call_args.kwargs["path"]
        assert path.startswith(f"{HOUSEHOLD_ID}/")
        assert path.endswith("/original.jpg")


# ── get_receipt ──


class TestGetReceipt:
    @pytest.mark.asyncio
    async def test_returns_receipt_with_signed_url(
        self, fake_pool, fake_supabase, fake_repo
    ):
        """get_receipt populates image_url from the signed URL generator."""
        receipt_id = uuid4()
        fake_repo.get_by_id = AsyncMock(
            return_value=_make_row(receipt_id, "path/to/original.jpg")
        )

        service = ReceiptService(fake_pool)
        result = await service.get_receipt(receipt_id, HOUSEHOLD_ID)

        assert result["image_url"] == "https://signed.example/receipts/x"
        assert result["items"] == []

    @pytest.mark.asyncio
    async def test_signed_url_failure_is_non_fatal(
        self, fake_pool, fake_supabase, fake_repo
    ):
        """create_signed_url raising -> image_url is None, no exception."""
        receipt_id = uuid4()
        fake_repo.get_by_id = AsyncMock(
            return_value=_make_row(receipt_id, "path/to/original.jpg")
        )
        bucket = fake_supabase.storage.from_.return_value
        bucket.create_signed_url = MagicMock(side_effect=RuntimeError("signing down"))

        service = ReceiptService(fake_pool)
        result = await service.get_receipt(receipt_id, HOUSEHOLD_ID)

        assert result["image_url"] is None
        assert result["items"] == []

    @pytest.mark.asyncio
    async def test_not_found_raises(self, fake_pool, fake_supabase, fake_repo):
        """Missing receipt -> NotFoundError."""
        fake_repo.get_by_id = AsyncMock(return_value=None)

        service = ReceiptService(fake_pool)
        with pytest.raises(NotFoundError):
            await service.get_receipt(uuid4(), HOUSEHOLD_ID)

    @pytest.mark.asyncio
    async def test_returns_empty_items_list(
        self, fake_pool, fake_supabase, fake_repo
    ):
        """No OCR yet -> items is always []."""
        receipt_id = uuid4()
        fake_repo.get_by_id = AsyncMock(
            return_value=_make_row(receipt_id, "path/to/original.jpg")
        )

        service = ReceiptService(fake_pool)
        result = await service.get_receipt(receipt_id, HOUSEHOLD_ID)
        assert result["items"] == []

    @pytest.mark.asyncio
    async def test_scopes_by_household(
        self, fake_pool, fake_supabase, fake_repo
    ):
        """get_by_id is called with the household_id from the auth context."""
        receipt_id = uuid4()
        fake_repo.get_by_id = AsyncMock(
            return_value=_make_row(receipt_id, "path/to/original.jpg")
        )

        service = ReceiptService(fake_pool)
        await service.get_receipt(receipt_id, HOUSEHOLD_ID)

        fake_repo.get_by_id.assert_called_once_with(receipt_id, HOUSEHOLD_ID)


# ── list_receipts ──


class TestListReceipts:
    @pytest.mark.asyncio
    async def test_returns_household_scoped_rows(
        self, fake_pool, fake_supabase, fake_repo
    ):
        """list_receipts passes household_id and returns rows from the repo."""
        rows = [
            _make_row(uuid4(), "a"),
            _make_row(uuid4(), "b"),
        ]
        fake_repo.list_by_household = AsyncMock(return_value=rows)

        service = ReceiptService(fake_pool)
        result = await service.list_receipts(HOUSEHOLD_ID)

        assert len(result) == 2
        call = fake_repo.list_by_household.call_args
        assert call.args[0] == HOUSEHOLD_ID or call.kwargs.get("household_id") == HOUSEHOLD_ID

    @pytest.mark.asyncio
    async def test_passes_limit_and_offset(
        self, fake_pool, fake_supabase, fake_repo
    ):
        """Pagination params are forwarded to the repo."""
        fake_repo.list_by_household = AsyncMock(return_value=[])

        service = ReceiptService(fake_pool)
        await service.list_receipts(HOUSEHOLD_ID, limit=50, offset=20)

        call = fake_repo.list_by_household.call_args
        assert call.kwargs.get("limit") == 50
        assert call.kwargs.get("offset") == 20

    @pytest.mark.asyncio
    async def test_default_pagination(
        self, fake_pool, fake_supabase, fake_repo
    ):
        """Default limit=100, offset=0 when not specified."""
        fake_repo.list_by_household = AsyncMock(return_value=[])

        service = ReceiptService(fake_pool)
        await service.list_receipts(HOUSEHOLD_ID)

        call = fake_repo.list_by_household.call_args
        assert call.kwargs.get("limit") == 100
        assert call.kwargs.get("offset") == 0


# ── Schema guardrails: storage_path must NOT leak ──


class TestResponseSchemaHidesStoragePath:
    def test_receipt_response_does_not_declare_storage_path(self):
        from app.schemas.receipts import ReceiptResponse
        assert "storage_path" not in ReceiptResponse.model_fields

    def test_receipt_list_item_does_not_declare_storage_path(self):
        from app.schemas.receipts import ReceiptListItem
        assert "storage_path" not in ReceiptListItem.model_fields

    def test_constructing_response_from_service_dict_drops_storage_path(self):
        """A service dict containing storage_path must not leak it to dump output."""
        from app.schemas.receipts import ReceiptResponse

        service_dict = {
            "id": uuid4(),
            "status": "uploaded",
            "store_name": None,
            "receipt_date": None,
            "total_amount": None,
            "storage_path": "household/receipt/original.jpg",  # internal field
            "file_name": "receipt.jpg",
            "mime_type": "image/jpeg",
            "created_at": datetime.now(timezone.utc),
        }
        response = ReceiptResponse(**service_dict)
        dumped = response.model_dump()
        assert "storage_path" not in dumped


# ── parse_receipt ──


class TestParseReceipt:
    @pytest.mark.asyncio
    async def test_happy_path_from_uploaded(
        self, fake_pool, fake_supabase, fake_repo, fake_parser, fake_parsed_receipt
    ):
        """uploaded → processing → ocr_complete. Items persisted. Response includes items."""
        receipt_id = uuid4()
        base_row = _make_row(receipt_id, f"{HOUSEHOLD_ID}/{receipt_id}/original.jpg")
        base_row["status"] = "uploaded"
        fake_repo.get_by_id = AsyncMock(return_value=base_row)
        fake_repo.mark_processing = AsyncMock(
            return_value={"id": receipt_id, "prior_status": "uploaded"}
        )
        fake_repo.update_parse_result = AsyncMock(
            return_value=_make_parsed_row(receipt_id)
        )
        fake_repo.insert_items = AsyncMock(
            return_value=[
                _make_item_row(receipt_id, 1, "Maelk", Decimal("12.50")),
                _make_item_row(receipt_id, 2, "Broed", Decimal("25.00")),
            ]
        )

        service = ReceiptService(fake_pool)
        result = await service.parse_receipt(receipt_id, HOUSEHOLD_ID)

        # Status lifecycle
        fake_repo.mark_processing.assert_awaited_once_with(receipt_id, HOUSEHOLD_ID)
        fake_repo.update_parse_result.assert_awaited_once()
        update_kwargs = fake_repo.update_parse_result.call_args.kwargs
        assert update_kwargs["store_name"] == "Netto"
        assert update_kwargs["receipt_date"] == date(2026, 4, 5)
        assert update_kwargs["total_amount"] == Decimal("150.00")
        assert update_kwargs["ocr_raw_text"] == fake_parsed_receipt.raw_text
        assert update_kwargs["ocr_provider"] == "anthropic"  # from settings
        assert update_kwargs["ocr_confidence"] == Decimal("0.9")

        # Items replaced atomically: delete THEN insert
        fake_repo.delete_items.assert_awaited_once_with(receipt_id)
        fake_repo.insert_items.assert_awaited_once()
        item_dicts = fake_repo.insert_items.call_args.args[1]
        assert len(item_dicts) == 2
        assert item_dicts[0]["description"] == "Maelk"
        assert item_dicts[0]["confidence"] == 0.95
        assert item_dicts[0]["requires_review"] is True
        assert item_dicts[0]["suggested_category_id"] is None

        # Response shape
        assert result["status"] == "ocr_complete"
        assert len(result["items"]) == 2
        assert result["duplicate_candidates"] == []

        # Parser was called with the downloaded bytes
        fake_parser.parse.assert_awaited_once_with(b"fake image bytes", "image/jpeg")

    @pytest.mark.asyncio
    async def test_rejects_not_found(
        self, fake_pool, fake_supabase, fake_repo, fake_parser
    ):
        """Missing receipt → NotFoundError, no parser call."""
        fake_repo.get_by_id = AsyncMock(return_value=None)

        service = ReceiptService(fake_pool)
        with pytest.raises(NotFoundError):
            await service.parse_receipt(uuid4(), HOUSEHOLD_ID)

        assert fake_parser.parse.call_count == 0
        assert fake_repo.mark_processing.call_count == 0

    @pytest.mark.asyncio
    async def test_rejects_when_cas_fails(
        self, fake_pool, fake_supabase, fake_repo, fake_parser
    ):
        """mark_processing CAS returns None (locked status) → ConflictError."""
        receipt_id = uuid4()
        row = _make_row(receipt_id, "path")
        row["status"] = "reviewed"
        fake_repo.get_by_id = AsyncMock(return_value=row)
        fake_repo.mark_processing = AsyncMock(return_value=None)  # CAS failed

        service = ReceiptService(fake_pool)
        with pytest.raises(ConflictError, match="reviewed"):
            await service.parse_receipt(receipt_id, HOUSEHOLD_ID)

        # No download, no parse
        bucket = fake_supabase.storage.from_.return_value
        assert bucket.download.call_count == 0
        assert fake_parser.parse.call_count == 0

    @pytest.mark.asyncio
    async def test_allows_re_parse_from_ocr_complete(
        self, fake_pool, fake_supabase, fake_repo, fake_parser
    ):
        """Re-parsing an ocr_complete receipt deletes old items then inserts new."""
        receipt_id = uuid4()
        row = _make_row(receipt_id, "path")
        row["status"] = "ocr_complete"
        fake_repo.get_by_id = AsyncMock(return_value=row)
        fake_repo.mark_processing = AsyncMock(
            return_value={"id": receipt_id, "prior_status": "ocr_complete"}
        )
        fake_repo.update_parse_result = AsyncMock(
            return_value=_make_parsed_row(receipt_id)
        )

        service = ReceiptService(fake_pool)
        await service.parse_receipt(receipt_id, HOUSEHOLD_ID)

        fake_repo.delete_items.assert_awaited_once_with(receipt_id)
        fake_repo.update_parse_result.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_allows_retry_after_failed(
        self, fake_pool, fake_supabase, fake_repo, fake_parser
    ):
        """A previously failed receipt can retry."""
        receipt_id = uuid4()
        row = _make_row(receipt_id, "path")
        row["status"] = "failed"
        fake_repo.get_by_id = AsyncMock(return_value=row)
        fake_repo.mark_processing = AsyncMock(
            return_value={"id": receipt_id, "prior_status": "failed"}
        )
        fake_repo.update_parse_result = AsyncMock(
            return_value=_make_parsed_row(receipt_id)
        )

        service = ReceiptService(fake_pool)
        result = await service.parse_receipt(receipt_id, HOUSEHOLD_ID)
        assert result["status"] == "ocr_complete"

    @pytest.mark.asyncio
    async def test_storage_download_failure_marks_failed_from_uploaded(
        self, fake_pool, fake_supabase, fake_repo, fake_parser
    ):
        """download raises from uploaded → mark_failed with prior_status='uploaded'."""
        receipt_id = uuid4()
        row = _make_row(receipt_id, "path")
        row["status"] = "uploaded"
        fake_repo.get_by_id = AsyncMock(return_value=row)
        fake_repo.mark_processing = AsyncMock(
            return_value={"id": receipt_id, "prior_status": "uploaded"}
        )
        bucket = fake_supabase.storage.from_.return_value
        bucket.download = MagicMock(side_effect=RuntimeError("S3 down"))

        service = ReceiptService(fake_pool)
        with pytest.raises(AppError, match="Storage download failed"):
            await service.parse_receipt(receipt_id, HOUSEHOLD_ID)

        # Parser never called
        assert fake_parser.parse.call_count == 0
        # mark_failed called with prior_status='uploaded'
        fake_repo.mark_failed.assert_awaited_once()
        mf_args = fake_repo.mark_failed.call_args.args
        assert mf_args[0] == receipt_id
        assert mf_args[1] == HOUSEHOLD_ID
        assert "Storage download failed" in mf_args[2]
        assert mf_args[3] == "uploaded"

    @pytest.mark.asyncio
    async def test_parser_failure_marks_failed_from_uploaded(
        self, fake_pool, fake_supabase, fake_repo, fake_parser
    ):
        """Parser raises from uploaded → mark_failed, no delete_items, no update."""
        receipt_id = uuid4()
        row = _make_row(receipt_id, "path")
        row["status"] = "uploaded"
        fake_repo.get_by_id = AsyncMock(return_value=row)
        fake_repo.mark_processing = AsyncMock(
            return_value={"id": receipt_id, "prior_status": "uploaded"}
        )
        fake_parser.parse = AsyncMock(side_effect=RuntimeError("claude timeout"))

        service = ReceiptService(fake_pool)
        with pytest.raises(AppError, match="Receipt parsing failed"):
            await service.parse_receipt(receipt_id, HOUSEHOLD_ID)

        fake_repo.mark_failed.assert_awaited_once()
        assert fake_repo.mark_failed.call_args.args[3] == "uploaded"
        # Old items were NOT touched
        assert fake_repo.delete_items.call_count == 0
        assert fake_repo.update_parse_result.call_count == 0
        assert fake_repo.insert_items.call_count == 0

    @pytest.mark.asyncio
    async def test_reparse_failure_from_ocr_complete_preserves_data(
        self, fake_pool, fake_supabase, fake_repo, fake_parser
    ):
        """v1 preservation rule: re-parse failure from ocr_complete keeps old data.

        mark_failed is called with prior_status='ocr_complete' (repo branches
        on this and reverts status to ocr_complete instead of moving to failed).
        delete_items, update_parse_result, and insert_items are never called,
        so the previous OCR fields and receipt_items rows remain intact.
        """
        receipt_id = uuid4()
        row = _make_row(receipt_id, "path")
        row["status"] = "ocr_complete"
        fake_repo.get_by_id = AsyncMock(return_value=row)
        fake_repo.mark_processing = AsyncMock(
            return_value={"id": receipt_id, "prior_status": "ocr_complete"}
        )
        fake_parser.parse = AsyncMock(side_effect=RuntimeError("claude down"))

        service = ReceiptService(fake_pool)
        with pytest.raises(AppError, match="Receipt parsing failed"):
            await service.parse_receipt(receipt_id, HOUSEHOLD_ID)

        # mark_failed was called with prior_status='ocr_complete'.
        # The repository's mark_failed implementation branches on this and
        # preserves all OCR fields.
        fake_repo.mark_failed.assert_awaited_once()
        assert fake_repo.mark_failed.call_args.args[3] == "ocr_complete"
        # Critical: old data must be untouched
        assert fake_repo.delete_items.call_count == 0
        assert fake_repo.update_parse_result.call_count == 0
        assert fake_repo.insert_items.call_count == 0

    @pytest.mark.asyncio
    async def test_reparse_failure_from_failed_keeps_failed_status(
        self, fake_pool, fake_supabase, fake_repo, fake_parser
    ):
        """If prior_status='failed', another failure stays in failed."""
        receipt_id = uuid4()
        row = _make_row(receipt_id, "path")
        row["status"] = "failed"
        fake_repo.get_by_id = AsyncMock(return_value=row)
        fake_repo.mark_processing = AsyncMock(
            return_value={"id": receipt_id, "prior_status": "failed"}
        )
        fake_parser.parse = AsyncMock(side_effect=RuntimeError("claude down"))

        service = ReceiptService(fake_pool)
        with pytest.raises(AppError):
            await service.parse_receipt(receipt_id, HOUSEHOLD_ID)

        fake_repo.mark_failed.assert_awaited_once()
        assert fake_repo.mark_failed.call_args.args[3] == "failed"

    @pytest.mark.asyncio
    async def test_duplicate_candidates_in_response(
        self, fake_pool, fake_supabase, fake_repo, fake_parser
    ):
        """If list_for_duplicate_check returns a match, it appears in response."""
        receipt_id = uuid4()
        dup_id = uuid4()
        row = _make_row(receipt_id, "path")
        row["status"] = "uploaded"
        fake_repo.get_by_id = AsyncMock(return_value=row)
        fake_repo.mark_processing = AsyncMock(
            return_value={"id": receipt_id, "prior_status": "uploaded"}
        )
        fake_repo.update_parse_result = AsyncMock(
            return_value=_make_parsed_row(receipt_id)
        )
        fake_repo.list_for_duplicate_check = AsyncMock(
            return_value=[
                {
                    "id": dup_id,
                    "store_name": "Netto",
                    "receipt_date": "2026-04-05",
                    "total_amount": "150.00",
                }
            ]
        )

        service = ReceiptService(fake_pool)
        result = await service.parse_receipt(receipt_id, HOUSEHOLD_ID)

        assert len(result["duplicate_candidates"]) == 1
        assert result["duplicate_candidates"][0]["id"] == dup_id
        # Dedup query excludes the current receipt
        fake_repo.list_for_duplicate_check.assert_awaited_once_with(
            HOUSEHOLD_ID, exclude_id=receipt_id
        )

    @pytest.mark.asyncio
    async def test_empty_items_from_parser(
        self, fake_pool, fake_supabase, fake_repo, fake_parser
    ):
        """Parser returns 0 items → still transitions to ocr_complete."""
        receipt_id = uuid4()
        row = _make_row(receipt_id, "path")
        row["status"] = "uploaded"
        fake_repo.get_by_id = AsyncMock(return_value=row)
        fake_repo.mark_processing = AsyncMock(
            return_value={"id": receipt_id, "prior_status": "uploaded"}
        )
        fake_parser.parse = AsyncMock(return_value=ParsedReceipt(
            store_name="Empty Store", items=[], raw_text="only header text", confidence=0.5,
        ))
        fake_repo.update_parse_result = AsyncMock(
            return_value=_make_parsed_row(receipt_id)
        )
        fake_repo.insert_items = AsyncMock(return_value=[])

        service = ReceiptService(fake_pool)
        result = await service.parse_receipt(receipt_id, HOUSEHOLD_ID)

        assert result["status"] == "ocr_complete"
        # insert_items called with empty list
        assert fake_repo.insert_items.call_args.args[1] == []

    @pytest.mark.asyncio
    async def test_persists_ocr_provider_from_config(
        self, fake_pool, fake_supabase, fake_repo, fake_parser
    ):
        """update_parse_result is called with ocr_provider=settings.ocr_provider."""
        receipt_id = uuid4()
        row = _make_row(receipt_id, "path")
        row["status"] = "uploaded"
        fake_repo.get_by_id = AsyncMock(return_value=row)
        fake_repo.mark_processing = AsyncMock(
            return_value={"id": receipt_id, "prior_status": "uploaded"}
        )
        fake_repo.update_parse_result = AsyncMock(
            return_value=_make_parsed_row(receipt_id)
        )

        service = ReceiptService(fake_pool)
        await service.parse_receipt(receipt_id, HOUSEHOLD_ID)

        # settings default is 'anthropic' (conftest doesn't override OCR_PROVIDER)
        assert (
            fake_repo.update_parse_result.call_args.kwargs["ocr_provider"]
            == "anthropic"
        )


# ── Helpers for phase-3 tests ──


def _make_item_dict(
    item_id: UUID,
    description: str = "Maelk",
    total_price: Decimal = Decimal("12.50"),
    suggested_category_id=None,
    confidence=None,
    requires_review: bool = True,
):
    return {
        "id": item_id,
        "receipt_id": uuid4(),
        "line_number": 1,
        "description": description,
        "quantity": None,
        "unit_price": None,
        "total_price": total_price,
        "suggested_category_id": suggested_category_id,
        "confidence": confidence,
        "requires_review": requires_review,
        "user_confirmed_category_id": None,
        "is_excluded": False,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def _make_category_row(cat_id: UUID, name: str = "Dagligvarer"):
    return {
        "id": cat_id,
        "household_id": HOUSEHOLD_ID,
        "type": "expense",
        "name": name,
        "icon": None,
        "sort_order": 0,
        "archived_at": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def _make_ocr_complete_row(receipt_id: UUID):
    row = _make_row(receipt_id, f"{HOUSEHOLD_ID}/{receipt_id}/original.jpg")
    row["status"] = "ocr_complete"
    row["store_name"] = "Netto"
    row["receipt_date"] = date(2026, 4, 5)
    row["total_amount"] = Decimal("150.00")
    return row


# ── categorize_receipt ──


class TestCategorizeReceipt:
    @pytest.mark.asyncio
    async def test_happy_path(
        self,
        fake_pool,
        fake_supabase,
        fake_repo,
        fake_category_repo,
        fake_categorizer,
    ):
        """All items get valid suggestions → full-refresh update, review payload returned."""
        receipt_id = uuid4()
        item_1 = uuid4()
        item_2 = uuid4()
        cat_groceries = uuid4()
        cat_cleaning = uuid4()

        fake_repo.get_by_id = AsyncMock(return_value=_make_ocr_complete_row(receipt_id))
        fake_repo.list_items_by_receipt = AsyncMock(return_value=[
            _make_item_dict(item_1, description="Maelk", total_price=Decimal("12.50")),
            _make_item_dict(item_2, description="Vanish", total_price=Decimal("45.00")),
        ])
        fake_category_repo.list_by_household = AsyncMock(return_value=[
            _make_category_row(cat_groceries, "Dagligvarer"),
            _make_category_row(cat_cleaning, "Rengoring"),
        ])
        fake_categorizer.categorize = AsyncMock(return_value=CategorizationResult(
            suggestions=[
                CategorySuggestion(
                    receipt_item_id=item_1,
                    suggested_category_id=cat_groceries,
                    confidence=0.95,
                ),
                CategorySuggestion(
                    receipt_item_id=item_2,
                    suggested_category_id=cat_cleaning,
                    confidence=0.72,
                ),
            ]
        ))
        # For the review payload load
        fake_repo.list_items_with_category_names = AsyncMock(return_value=[
            {
                **_make_item_dict(
                    item_1, description="Maelk",
                    suggested_category_id=cat_groceries,
                    confidence=0.95,
                    requires_review=False,
                ),
                "suggested_category_name": "Dagligvarer",
                "user_confirmed_category_name": None,
            },
            {
                **_make_item_dict(
                    item_2, description="Vanish",
                    suggested_category_id=cat_cleaning,
                    confidence=0.72,
                    requires_review=True,
                ),
                "suggested_category_name": "Rengoring",
                "user_confirmed_category_name": None,
            },
        ])

        service = ReceiptService(fake_pool)
        result = await service.categorize_receipt(receipt_id, HOUSEHOLD_ID)

        # Verify update_item_suggestions received a full-refresh list
        fake_repo.update_item_suggestions.assert_awaited_once()
        updates = fake_repo.update_item_suggestions.call_args.args[0]
        assert len(updates) == 2
        by_id = {u["id"]: u for u in updates}
        # item_1: high confidence → requires_review False
        assert by_id[item_1]["suggested_category_id"] == cat_groceries
        assert by_id[item_1]["confidence"] == 0.95
        assert by_id[item_1]["requires_review"] is False
        # item_2: low confidence → requires_review True
        assert by_id[item_2]["suggested_category_id"] == cat_cleaning
        assert by_id[item_2]["confidence"] == 0.72
        assert by_id[item_2]["requires_review"] is True

        # Response shape
        assert result["status"] == "ocr_complete"
        assert len(result["items"]) == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_status", ["uploaded", "processing", "reviewed", "posted", "failed"])
    async def test_rejects_non_ocr_complete_status(
        self,
        fake_pool,
        fake_supabase,
        fake_repo,
        fake_category_repo,
        fake_categorizer,
        bad_status,
    ):
        """Any status other than ocr_complete → 409 ConflictError."""
        receipt_id = uuid4()
        row = _make_row(receipt_id, "path")
        row["status"] = bad_status
        fake_repo.get_by_id = AsyncMock(return_value=row)

        service = ReceiptService(fake_pool)
        with pytest.raises(ConflictError):
            await service.categorize_receipt(receipt_id, HOUSEHOLD_ID)

        # No AI call, no updates
        assert fake_categorizer.categorize.call_count == 0
        assert fake_repo.update_item_suggestions.call_count == 0

    @pytest.mark.asyncio
    async def test_not_found(
        self,
        fake_pool,
        fake_supabase,
        fake_repo,
        fake_category_repo,
        fake_categorizer,
    ):
        fake_repo.get_by_id = AsyncMock(return_value=None)

        service = ReceiptService(fake_pool)
        with pytest.raises(NotFoundError):
            await service.categorize_receipt(uuid4(), HOUSEHOLD_ID)

        assert fake_categorizer.categorize.call_count == 0

    @pytest.mark.asyncio
    async def test_unknown_category_from_ai_is_dropped_and_item_reset(
        self,
        fake_pool,
        fake_supabase,
        fake_repo,
        fake_category_repo,
        fake_categorizer,
    ):
        """AI returns a category_id that is not in the active expense set → item reset."""
        receipt_id = uuid4()
        item_1 = uuid4()
        known_cat = uuid4()
        unknown_cat = uuid4()

        fake_repo.get_by_id = AsyncMock(return_value=_make_ocr_complete_row(receipt_id))
        fake_repo.list_items_by_receipt = AsyncMock(return_value=[
            _make_item_dict(item_1),
        ])
        fake_category_repo.list_by_household = AsyncMock(return_value=[
            _make_category_row(known_cat),
        ])
        fake_categorizer.categorize = AsyncMock(return_value=CategorizationResult(
            suggestions=[
                CategorySuggestion(
                    receipt_item_id=item_1,
                    suggested_category_id=unknown_cat,  # not in active set
                    confidence=0.99,
                ),
            ]
        ))
        fake_repo.list_items_with_category_names = AsyncMock(return_value=[])

        service = ReceiptService(fake_pool)
        await service.categorize_receipt(receipt_id, HOUSEHOLD_ID)

        updates = fake_repo.update_item_suggestions.call_args.args[0]
        assert len(updates) == 1
        assert updates[0]["id"] == item_1
        assert updates[0]["suggested_category_id"] is None
        assert updates[0]["confidence"] is None
        assert updates[0]["requires_review"] is True

    @pytest.mark.asyncio
    async def test_suggestion_for_unknown_item_dropped(
        self,
        fake_pool,
        fake_supabase,
        fake_repo,
        fake_category_repo,
        fake_categorizer,
    ):
        """AI returns a suggestion for an item id not in the receipt → dropped."""
        receipt_id = uuid4()
        item_1 = uuid4()
        cat_id = uuid4()
        ghost_item = uuid4()

        fake_repo.get_by_id = AsyncMock(return_value=_make_ocr_complete_row(receipt_id))
        fake_repo.list_items_by_receipt = AsyncMock(return_value=[
            _make_item_dict(item_1),
        ])
        fake_category_repo.list_by_household = AsyncMock(return_value=[
            _make_category_row(cat_id),
        ])
        fake_categorizer.categorize = AsyncMock(return_value=CategorizationResult(
            suggestions=[
                CategorySuggestion(
                    receipt_item_id=ghost_item,
                    suggested_category_id=cat_id,
                    confidence=0.95,
                ),
            ]
        ))
        fake_repo.list_items_with_category_names = AsyncMock(return_value=[])

        service = ReceiptService(fake_pool)
        await service.categorize_receipt(receipt_id, HOUSEHOLD_ID)

        # item_1 was not suggested for → reset
        updates = fake_repo.update_item_suggestions.call_args.args[0]
        assert len(updates) == 1
        assert updates[0]["id"] == item_1
        assert updates[0]["suggested_category_id"] is None
        assert updates[0]["requires_review"] is True

    @pytest.mark.asyncio
    async def test_recategorization_full_refresh(
        self,
        fake_pool,
        fake_supabase,
        fake_repo,
        fake_category_repo,
        fake_categorizer,
    ):
        """Item has stale suggestion from prior run; new run suggests only a subset.

        The untouched item must be reset to (NULL, NULL, True).
        """
        receipt_id = uuid4()
        item_a = uuid4()
        item_b = uuid4()
        stale_cat = uuid4()
        fresh_cat = uuid4()

        fake_repo.get_by_id = AsyncMock(return_value=_make_ocr_complete_row(receipt_id))
        fake_repo.list_items_by_receipt = AsyncMock(return_value=[
            # item_a had a prior suggestion that is still in the row
            _make_item_dict(
                item_a,
                suggested_category_id=stale_cat,
                confidence=0.9,
                requires_review=False,
            ),
            _make_item_dict(item_b),
        ])
        fake_category_repo.list_by_household = AsyncMock(return_value=[
            _make_category_row(fresh_cat),
        ])
        # New run produces a suggestion only for item_b
        fake_categorizer.categorize = AsyncMock(return_value=CategorizationResult(
            suggestions=[
                CategorySuggestion(
                    receipt_item_id=item_b,
                    suggested_category_id=fresh_cat,
                    confidence=0.93,
                ),
            ]
        ))
        fake_repo.list_items_with_category_names = AsyncMock(return_value=[])

        service = ReceiptService(fake_pool)
        await service.categorize_receipt(receipt_id, HOUSEHOLD_ID)

        updates = fake_repo.update_item_suggestions.call_args.args[0]
        by_id = {u["id"]: u for u in updates}
        # item_a: stale suggestion cleared
        assert by_id[item_a]["suggested_category_id"] is None
        assert by_id[item_a]["confidence"] is None
        assert by_id[item_a]["requires_review"] is True
        # item_b: new suggestion applied
        assert by_id[item_b]["suggested_category_id"] == fresh_cat
        assert by_id[item_b]["requires_review"] is False

    @pytest.mark.asyncio
    async def test_review_not_bypassed_at_receipt_level(
        self,
        fake_pool,
        fake_supabase,
        fake_repo,
        fake_category_repo,
        fake_categorizer,
    ):
        """Even with every item at requires_review=False, receipt stays ocr_complete.

        The service must not transition the receipt or create any transactions.
        """
        receipt_id = uuid4()
        item_1 = uuid4()
        cat_id = uuid4()

        base_row = _make_ocr_complete_row(receipt_id)
        fake_repo.get_by_id = AsyncMock(return_value=base_row)
        fake_repo.list_items_by_receipt = AsyncMock(return_value=[
            _make_item_dict(item_1),
        ])
        fake_category_repo.list_by_household = AsyncMock(return_value=[
            _make_category_row(cat_id),
        ])
        fake_categorizer.categorize = AsyncMock(return_value=CategorizationResult(
            suggestions=[
                CategorySuggestion(
                    receipt_item_id=item_1,
                    suggested_category_id=cat_id,
                    confidence=0.99,
                ),
            ]
        ))
        # Review payload still returns the same ocr_complete row
        fake_repo.list_items_with_category_names = AsyncMock(return_value=[])

        service = ReceiptService(fake_pool)
        result = await service.categorize_receipt(receipt_id, HOUSEHOLD_ID)

        # Observable behavior only — no future-phase methods referenced.
        # 1. Returned receipt status stays ocr_complete.
        assert result["status"] == "ocr_complete"
        # 2. No transaction-related repo methods exist on the mock being called
        #    (these aren't even declared on fake_repo — accessing them as
        #    attributes creates new MagicMock children, so assert on the
        #    methods we DID declare instead).
        # 3. Only phase-3 repo methods were called:
        assert fake_repo.update_item_suggestions.call_count == 1
        # And none of the parse/upload methods were touched:
        assert fake_repo.update_parse_result.call_count == 0
        assert fake_repo.delete_items.call_count == 0
        assert fake_repo.insert_items.call_count == 0
        assert fake_repo.mark_processing.call_count == 0
        assert fake_repo.mark_failed.call_count == 0

    @pytest.mark.asyncio
    async def test_ai_failure_returns_502_and_no_updates(
        self,
        fake_pool,
        fake_supabase,
        fake_repo,
        fake_category_repo,
        fake_categorizer,
    ):
        receipt_id = uuid4()
        item_1 = uuid4()
        fake_repo.get_by_id = AsyncMock(return_value=_make_ocr_complete_row(receipt_id))
        fake_repo.list_items_by_receipt = AsyncMock(return_value=[
            _make_item_dict(item_1),
        ])
        fake_category_repo.list_by_household = AsyncMock(return_value=[
            _make_category_row(uuid4()),
        ])
        fake_categorizer.categorize = AsyncMock(side_effect=RuntimeError("claude down"))

        service = ReceiptService(fake_pool)
        with pytest.raises(AppError, match="Receipt categorization failed"):
            await service.categorize_receipt(receipt_id, HOUSEHOLD_ID)

        assert fake_repo.update_item_suggestions.call_count == 0

    @pytest.mark.asyncio
    async def test_only_active_expense_categories_are_offered(
        self,
        fake_pool,
        fake_supabase,
        fake_repo,
        fake_category_repo,
        fake_categorizer,
    ):
        """Service calls category repo with type_filter='expense', include_archived=False."""
        receipt_id = uuid4()
        item_id = uuid4()
        cat_id = uuid4()
        fake_repo.get_by_id = AsyncMock(return_value=_make_ocr_complete_row(receipt_id))
        fake_repo.list_items_by_receipt = AsyncMock(return_value=[
            _make_item_dict(item_id),
        ])
        fake_category_repo.list_by_household = AsyncMock(return_value=[
            _make_category_row(cat_id),
        ])
        fake_categorizer.categorize = AsyncMock(return_value=CategorizationResult(
            suggestions=[
                CategorySuggestion(
                    receipt_item_id=item_id,
                    suggested_category_id=cat_id,
                    confidence=0.9,
                ),
            ]
        ))
        fake_repo.list_items_with_category_names = AsyncMock(return_value=[])
        fake_repo.list_for_duplicate_check = AsyncMock(return_value=[])

        service = ReceiptService(fake_pool)
        await service.categorize_receipt(receipt_id, HOUSEHOLD_ID)

        fake_category_repo.list_by_household.assert_awaited_once()
        call = fake_category_repo.list_by_household.call_args
        assert call.kwargs.get("type_filter") == "expense"
        assert call.kwargs.get("include_archived") is False

    @pytest.mark.asyncio
    async def test_user_confirmed_category_id_is_never_touched(
        self,
        fake_pool,
        fake_supabase,
        fake_repo,
        fake_category_repo,
        fake_categorizer,
    ):
        """The update dicts must not contain user_confirmed_category_id."""
        receipt_id = uuid4()
        item_1 = uuid4()
        cat_id = uuid4()

        fake_repo.get_by_id = AsyncMock(return_value=_make_ocr_complete_row(receipt_id))
        fake_repo.list_items_by_receipt = AsyncMock(return_value=[
            _make_item_dict(item_1),
        ])
        fake_category_repo.list_by_household = AsyncMock(return_value=[
            _make_category_row(cat_id),
        ])
        fake_categorizer.categorize = AsyncMock(return_value=CategorizationResult(
            suggestions=[
                CategorySuggestion(
                    receipt_item_id=item_1,
                    suggested_category_id=cat_id,
                    confidence=0.95,
                ),
            ]
        ))
        fake_repo.list_items_with_category_names = AsyncMock(return_value=[])

        service = ReceiptService(fake_pool)
        await service.categorize_receipt(receipt_id, HOUSEHOLD_ID)

        updates = fake_repo.update_item_suggestions.call_args.args[0]
        for update in updates:
            assert "user_confirmed_category_id" not in update

    @pytest.mark.asyncio
    async def test_duplicate_candidates_in_response(
        self,
        fake_pool,
        fake_supabase,
        fake_repo,
        fake_category_repo,
        fake_categorizer,
    ):
        """list_for_duplicate_check matches → duplicate_candidates populated."""
        receipt_id = uuid4()
        dup_id = uuid4()
        fake_repo.get_by_id = AsyncMock(return_value=_make_ocr_complete_row(receipt_id))
        fake_repo.list_items_by_receipt = AsyncMock(return_value=[])
        fake_category_repo.list_by_household = AsyncMock(return_value=[
            _make_category_row(uuid4()),
        ])
        fake_repo.list_items_with_category_names = AsyncMock(return_value=[])
        fake_repo.list_for_duplicate_check = AsyncMock(return_value=[
            {
                "id": dup_id,
                "store_name": "Netto",
                "receipt_date": "2026-04-05",
                "total_amount": "150.00",
            }
        ])

        service = ReceiptService(fake_pool)
        result = await service.categorize_receipt(receipt_id, HOUSEHOLD_ID)

        assert len(result["duplicate_candidates"]) == 1
        assert result["duplicate_candidates"][0]["id"] == dup_id

    @pytest.mark.asyncio
    async def test_zero_expense_categories_rejects(
        self, fake_pool, fake_supabase, fake_repo, fake_category_repo,
        fake_categorizer,
    ):
        """Household with no active expense categories → 422, AI never called."""
        receipt_id = uuid4()
        fake_repo.get_by_id = AsyncMock(return_value=_make_ocr_complete_row(receipt_id))
        fake_repo.list_items_by_receipt = AsyncMock(return_value=[
            _make_item_dict(uuid4(), description="Maelk"),
        ])
        fake_category_repo.list_by_household = AsyncMock(return_value=[])

        service = ReceiptService(fake_pool)
        with pytest.raises(ValidationError, match="no active expense categories"):
            await service.categorize_receipt(receipt_id, HOUSEHOLD_ID)

        fake_categorizer.categorize.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_one_expense_category_proceeds(
        self, fake_pool, fake_supabase, fake_repo, fake_category_repo,
        fake_categorizer,
    ):
        """Boundary: exactly 1 active expense category → categorization proceeds."""
        receipt_id = uuid4()
        item_id = uuid4()
        cat_id = uuid4()

        fake_repo.get_by_id = AsyncMock(return_value=_make_ocr_complete_row(receipt_id))
        fake_repo.list_items_by_receipt = AsyncMock(return_value=[
            _make_item_dict(item_id, description="Maelk"),
        ])
        fake_category_repo.list_by_household = AsyncMock(return_value=[
            _make_category_row(cat_id, "Dagligvarer"),
        ])
        fake_categorizer.categorize = AsyncMock(
            return_value=CategorizationResult(suggestions=[
                CategorySuggestion(
                    receipt_item_id=item_id,
                    suggested_category_id=cat_id,
                    confidence=0.9,
                ),
            ])
        )
        fake_repo.list_items_with_category_names = AsyncMock(return_value=[])
        fake_repo.list_for_duplicate_check = AsyncMock(return_value=[])

        service = ReceiptService(fake_pool)
        await service.categorize_receipt(receipt_id, HOUSEHOLD_ID)

        fake_categorizer.categorize.assert_awaited_once()


# ── get_review_payload ──


class TestGetReviewPayload:
    @pytest.mark.asyncio
    async def test_happy_path_ocr_complete(
        self, fake_pool, fake_supabase, fake_repo, fake_category_repo,
    ):
        receipt_id = uuid4()
        item_1 = uuid4()
        fake_repo.get_by_id = AsyncMock(return_value=_make_ocr_complete_row(receipt_id))
        fake_repo.list_items_with_category_names = AsyncMock(return_value=[
            {
                **_make_item_dict(item_1),
                "suggested_category_name": "Dagligvarer",
                "user_confirmed_category_name": None,
            },
        ])

        service = ReceiptService(fake_pool)
        result = await service.get_review_payload(receipt_id, HOUSEHOLD_ID)

        assert result["status"] == "ocr_complete"
        assert len(result["items"]) == 1
        assert result["items"][0]["suggested_category_name"] == "Dagligvarer"
        assert result["items"][0]["user_confirmed_category_name"] is None

    @pytest.mark.asyncio
    async def test_allows_reviewed_status(
        self, fake_pool, fake_supabase, fake_repo, fake_category_repo,
    ):
        """Re-reading an already-reviewed receipt is allowed."""
        receipt_id = uuid4()
        row = _make_ocr_complete_row(receipt_id)
        row["status"] = "reviewed"
        fake_repo.get_by_id = AsyncMock(return_value=row)
        fake_repo.list_items_with_category_names = AsyncMock(return_value=[])

        service = ReceiptService(fake_pool)
        result = await service.get_review_payload(receipt_id, HOUSEHOLD_ID)
        assert result["status"] == "reviewed"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_status", ["uploaded", "processing", "failed", "posted"])
    async def test_rejects_non_review_statuses(
        self, fake_pool, fake_supabase, fake_repo, fake_category_repo, bad_status,
    ):
        receipt_id = uuid4()
        row = _make_row(receipt_id, "path")
        row["status"] = bad_status
        fake_repo.get_by_id = AsyncMock(return_value=row)

        service = ReceiptService(fake_pool)
        with pytest.raises(ConflictError):
            await service.get_review_payload(receipt_id, HOUSEHOLD_ID)

    @pytest.mark.asyncio
    async def test_not_found(
        self, fake_pool, fake_supabase, fake_repo, fake_category_repo,
    ):
        fake_repo.get_by_id = AsyncMock(return_value=None)

        service = ReceiptService(fake_pool)
        with pytest.raises(NotFoundError):
            await service.get_review_payload(uuid4(), HOUSEHOLD_ID)

    @pytest.mark.asyncio
    async def test_signed_url_failure_is_non_fatal(
        self, fake_pool, fake_supabase, fake_repo, fake_category_repo,
    ):
        receipt_id = uuid4()
        fake_repo.get_by_id = AsyncMock(return_value=_make_ocr_complete_row(receipt_id))
        fake_repo.list_items_with_category_names = AsyncMock(return_value=[])
        bucket = fake_supabase.storage.from_.return_value
        bucket.create_signed_url = MagicMock(side_effect=RuntimeError("signing down"))

        service = ReceiptService(fake_pool)
        result = await service.get_review_payload(receipt_id, HOUSEHOLD_ID)
        assert result["image_url"] is None
        # Everything else still comes back
        assert result["status"] == "ocr_complete"
