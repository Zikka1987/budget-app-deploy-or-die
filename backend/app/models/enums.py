from enum import Enum


class TransactionType(str, Enum):
    INCOME = "income"
    EXPENSE = "expense"
    SAVINGS = "savings"


class ReceiptStatus(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    OCR_COMPLETE = "ocr_complete"
    REVIEWED = "reviewed"
    POSTED = "posted"
    FAILED = "failed"


class SavingsRuleType(str, Enum):
    PERCENT_OF_INCOME = "percent_of_income"
    FIXED_MONTHLY = "fixed_monthly"


class ProposalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    POSTED = "posted"


class TransactionSource(str, Enum):
    MANUAL_INCOME = "manual_income"
    MANUAL_EXPENSE = "manual_expense"
    MANUAL_SAVINGS = "manual_savings"
    RECEIPT = "receipt"
    SAVINGS_PROPOSAL = "savings_proposal"


class HouseholdInviteStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"
