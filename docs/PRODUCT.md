# Budget App - Product Definition

## 1. Product Summary

This app is a shared household budgeting system built to replace a manual Excel-based workflow for managing income, expenses, savings, receipts, and monthly budget tracking.

It is not a generic finance app and not a simple expense tracker.

It is a **budget-first household system** designed to preserve the clarity and control of a structured monthly budget while removing the slow manual work involved in receipt handling, categorization, and monthly reconciliation.

The app should feel simple, fast, structured, and trustworthy.

---

## 2. Core Problem

The current Excel system works, but the input process is too slow and manual.

Today, the household must manually:
- enter income
- read receipts
- decide categories
- split mixed receipts across categories
- update monthly budgets
- compare budgeted amounts with actual spending
- store and retrieve receipt history

The app exists to reduce that manual effort without sacrificing control.

The goal is not to automate away judgment. The goal is to make entry and review much faster while keeping the budgeting structure intact.

---

## 3. Product Goal

The app should become the household’s single system for:
- monthly budget planning
- income tracking
- expense logging
- savings tracking
- receipt storage
- budget-vs-actual reporting

The app should make it easy to answer questions like:
- How much income did we receive this month?
- How much did we spend on groceries?
- Are we over budget in any category?
- How much have we transferred to savings?
- What is left to allocate this month?
- What receipts do we have from a specific store?
- How much have we spent in a category over time?

---

## 4. Who the Product Is For

The app is designed for one shared household.

Primary usage model:
- two users
- one shared budget
- both users can contribute to the same household system

Examples:
- one person enters income
- the other uploads receipts
- both can see the same monthly budget
- both can review transactions and spending

The app is not designed as a broad multi-household or team finance platform.

---

## 5. Core Product Model

The product has exactly three financial domains:

### Income
Money coming into the household.

Examples:
- salary
- freelance or business income
- child support / benefits
- loans
- miscellaneous income

### Expenses
Money going out through spending.

Examples:
- rent
- groceries
- internet
- transport
- school
- coding
- work tools
- debt payments
- cleaning products
- subscriptions

### Savings
Money intentionally allocated into savings categories.

Examples:
- general savings
- sports savings
- clothing savings
- goal-based savings

This 3-part structure is fundamental to the product and should remain central.

---

## 6. Product Principles

### Budget-first, not transaction-first
The product is built around monthly planning and budget-vs-actual comparison, not just after-the-fact transaction logging.

### Control over automation
Automation should reduce manual work, but users must remain in control of what gets saved.

### Shared household by design
The product is built around shared household usage, not isolated single-user finance tracking.

### Structured, not generic
The product should support custom household categories and a clear budgeting framework rather than generic personal-finance defaults.

### Privacy-conscious
Financial data and receipt storage should be private, protected, and tightly scoped to the household.

---

## 7. What Makes the Product Different

This product is closer to a **budget engine with AI-assisted input** than a normal expense tracker.

Typical expense apps focus on:
- logging transactions after the fact
- generic categories
- lightweight summaries

This app is different because it is built around:
- structured monthly planning
- exact custom categories
- budget-vs-actual comparison
- savings planning
- shared household use
- split receipts
- required review before posting
- deterministic financial logic
- privacy-conscious design

---

## 8. Main Functional Areas

## A. Monthly budget planning
The product must support creating and managing monthly budgets.

That includes:
- creating a budget month
- copying the previous month’s category structure
- assigning planned amounts
- planning separately for income, expenses, and savings
- seeing what remains to be allocated

Each new month should start from the previous month’s active structure so the user does not rebuild the budget from scratch.

## B. Category management
Users must be able to:
- create categories
- rename categories
- archive categories
- organize categories by type:
  - income
  - expense
  - savings
- reorder categories

Renaming a category must preserve historical linkage. History must remain attached to the same underlying category identity.

## C. Manual income entry
Income should be entered manually and directly by the user.

Expected flow:
- choose month
- choose income category
- enter amount
- optionally add note
- save

Income is deterministic and should not depend on AI interpretation.

## D. Receipt-based expense entry
Receipt handling is one of the core value drivers of the product.

The app should allow the user to:
- take a receipt photo
- upload a receipt image
- extract receipt data
- identify purchased items
- suggest categories
- split one receipt across multiple categories
- review before saving

Example:
- potatoes → groceries
- milk → groceries
- bread → groceries
- Vanish → cleaning products

A single receipt must be able to produce multiple expense transactions.

## E. Review before posting
Receipt data must never be posted directly into the ledger without user confirmation.

Expected flow:
1. receipt uploaded
2. receipt interpreted
3. categories suggested
4. user reviews
5. user edits where needed
6. user confirms
7. transactions are saved

If the system is uncertain, the product should force manual resolution.

## F. Savings handling
Savings are a core product area, not a side feature.

The app should support:
- percentage-based savings
- fixed monthly savings categories
- manual savings entries

Savings must live inside the same budgeting system and update monthly budget visibility accordingly.

## G. Receipt archive and retrieval
The product should store receipts so they can be searched later.

Search dimensions should include:
- merchant/store
- category
- date
- amount

Users should be able to reopen the original receipt image and see related transaction details.

## H. Dashboard and reporting
The product should provide a clear monthly overview.

The dashboard should show:
- total income
- total expenses
- total savings
- planned vs actual by category
- remaining budget
- over-budget categories
- to-be-allocated amount
- savings rate

---

## 9. Core User Flows

### Flow 1: Start a new month
- create new budget month
- copy previous month’s active structure
- adjust planned amounts as needed

### Flow 2: Add income
- select month
- choose income category
- enter amount
- save

### Flow 3: Upload receipt
- take photo or upload image
- parse receipt
- suggest grouped categories
- review and edit
- confirm
- create expense transactions

### Flow 4: Generate savings
- calculate savings proposals
- review them
- approve or adjust
- create savings transactions

### Flow 5: View dashboard
- review budget vs actual
- inspect overspending
- monitor savings
- check current month health

### Flow 6: Search receipts or transactions
- search by merchant/category/date/amount
- open receipt image
- inspect related entries

---

## 10. Technical Philosophy

### Deterministic logic belongs in Python
Python/backend logic should be the source of truth for:
- calculations
- totals
- budget logic
- savings math
- month rollover
- posting rules
- duplicate detection
- reporting logic
- validation rules

This logic must be stable, testable, and predictable.

### AI supports non-deterministic interpretation
AI should only assist with:
- reading messy receipt images
- extracting items
- suggesting likely categories
- providing confidence estimates

AI is a helper, not the source of truth.

The product depends on this separation to provide both automation and reliability.

---

## 11. Cloud-Backed Product Model

The app should be cloud-backed because:
- two users need access to the same household data
- receipt images must be stored
- data must stay in sync across devices
- authentication matters
- search and archive access should work across sessions

At the same time, the product should remain privacy-conscious:
- protected access
- private storage
- controlled writes
- household-scoped access

---

## 12. UX Goals

The app should feel:
- simple
- fast
- structured
- easy to review
- trustworthy
- not overloaded with unnecessary finance features

It should not feel like bookkeeping software or a complicated accounting tool.

It should feel like:
- a clear monthly plan
- fast income entry
- convenient receipt input
- helpful review suggestions
- immediate budget updates

---

## 13. Success Criteria

The product is successful if it does these things well:
- income entry is quick
- receipt handling is much faster than Excel
- mixed receipts are handled correctly
- category management remains flexible
- the monthly budget is always clear
- both household members can use the same system
- category history stays intact through rename
- savings handling becomes easier and more automatic
- the app saves real time every month without reducing control

In practical terms, success means the household stops spending hours every month maintaining Excel manually while keeping the same budgeting clarity and structure they already value.

---

## 14. Non-Goals

This product is not intended to be:
- a generic finance super-app
- a bookkeeping/accounting platform
- a bank-sync-first product
- a multi-household platform in v1
- a feature-heavy personal-finance dashboard full of unrelated tools

The product should stay focused on structured household budgeting.

---

## 15. Relationship to Other Project Docs

- `CLAUDE.md` = project rules and implementation invariants
- `report.md` = current implementation status and technical handoff
- `docs/PRODUCT.md` = product vision and intended behavior

If implementation status changes, update `report.md`.

If product intent changes, update `docs/PRODUCT.md`.

Do not use `report.md` as the source of product vision.