# Skill: Receipt Parsing

## Purpose
Parse a receipt image into structured data using AI vision.

## Input
- Receipt image (JPEG, PNG, WebP, or PDF)
- MIME type

## Output (ParsedReceipt)
- store_name: merchant name
- receipt_date: date on receipt
- total_amount: grand total
- items: list of line items (description, quantity, unit_price, total_price)
- raw_text: full OCR text
- confidence: overall parse confidence (0.0-1.0)

## Rules
- Use the AI provider configured in `OCR_PROVIDER` (default: Anthropic)
- AI must return structured JSON matching ParsedReceipt schema
- Python validates all AI output before use
- Store raw_text on the receipt record for search
- Receipt language is Danish — prompt must handle Danish text
- Do not auto-post any data; this only extracts, never writes transactions

## Provider Interface
Implement `ReceiptParserBase.parse(image_bytes, mime_type) -> ParsedReceipt`
