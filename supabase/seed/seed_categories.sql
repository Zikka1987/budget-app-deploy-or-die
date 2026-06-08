-- ============================================================
-- Default categories for a Danish household budget
-- ============================================================
-- Run after creating a household. Replace the household_id placeholder.
-- These are sensible defaults; users can rename, reorder, or archive them.
-- ============================================================

-- Usage: Replace '00000000-0000-0000-0000-000000000000' with actual household_id

-- === Income Categories ===
INSERT INTO categories (household_id, type, name, sort_order) VALUES
    ('00000000-0000-0000-0000-000000000000', 'income', 'Loen', 1),           -- Salary
    ('00000000-0000-0000-0000-000000000000', 'income', 'Freelance', 2),
    ('00000000-0000-0000-0000-000000000000', 'income', 'Anden indkomst', 3); -- Other income

-- === Expense Categories ===
INSERT INTO categories (household_id, type, name, sort_order) VALUES
    ('00000000-0000-0000-0000-000000000000', 'expense', 'Husleje', 1),           -- Rent
    ('00000000-0000-0000-0000-000000000000', 'expense', 'El og vand', 2),        -- Electricity & water
    ('00000000-0000-0000-0000-000000000000', 'expense', 'Internet og mobil', 3), -- Internet & mobile
    ('00000000-0000-0000-0000-000000000000', 'expense', 'Forsikring', 4),        -- Insurance
    ('00000000-0000-0000-0000-000000000000', 'expense', 'Dagligvarer', 5),       -- Groceries
    ('00000000-0000-0000-0000-000000000000', 'expense', 'Transport', 6),         -- Transport
    ('00000000-0000-0000-0000-000000000000', 'expense', 'Rengoring', 7),         -- Cleaning products
    ('00000000-0000-0000-0000-000000000000', 'expense', 'Personlig pleje', 8),   -- Personal care
    ('00000000-0000-0000-0000-000000000000', 'expense', 'Toj', 9),              -- Clothing
    ('00000000-0000-0000-0000-000000000000', 'expense', 'Underholdning', 10),    -- Entertainment
    ('00000000-0000-0000-0000-000000000000', 'expense', 'Restauranter', 11),     -- Restaurants/dining
    ('00000000-0000-0000-0000-000000000000', 'expense', 'Sundhed', 12),          -- Health
    ('00000000-0000-0000-0000-000000000000', 'expense', 'Boern', 13),            -- Children
    ('00000000-0000-0000-0000-000000000000', 'expense', 'Kaeledyr', 14),         -- Pets
    ('00000000-0000-0000-0000-000000000000', 'expense', 'Gaver', 15),            -- Gifts
    ('00000000-0000-0000-0000-000000000000', 'expense', 'Abonnementer', 16),     -- Subscriptions
    ('00000000-0000-0000-0000-000000000000', 'expense', 'Diverse', 17);          -- Misc

-- === Savings Categories ===
INSERT INTO categories (household_id, type, name, sort_order) VALUES
    ('00000000-0000-0000-0000-000000000000', 'savings', 'Noedfond', 1),          -- Emergency fund
    ('00000000-0000-0000-0000-000000000000', 'savings', 'Ferie', 2),             -- Vacation
    ('00000000-0000-0000-0000-000000000000', 'savings', 'Opsparing generelt', 3); -- General savings
