# Skill: Category Rename

## Purpose
Rename a category while preserving historical linkage through stable ID.

## Process
1. Read current category name
2. Store old name as a new category_alias record
3. Update category name to the new name
4. Validate new name is unique within household + type

## Rules
- Category ID never changes — all transactions, budget lines, receipt items keep their FK
- Old name preserved in category_aliases for:
  - Search (user can find old receipts by old category name)
  - AI memory (AI categorizer can reference historical names)
- Uniqueness: new name must not conflict with another active category of the same type in the same household
- Archived categories' names can be reused
