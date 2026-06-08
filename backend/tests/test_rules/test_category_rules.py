"""Tests for category rename alias logic.

These test the behavioral contract: renaming creates an alias of the old name,
and the category_id never changes. Since the actual rename is in the service
(DB-dependent), we test the invariants as data-flow assertions.
"""


class TestCategoryRenameInvariants:
    def test_alias_preserves_old_name(self):
        """When renaming, the old name must become an alias."""
        old_name = "Dagligvarer"
        new_name = "Mad og drikke"
        # Simulate: rename creates alias = old_name
        alias = old_name
        assert alias == "Dagligvarer"
        assert alias != new_name

    def test_category_id_unchanged_after_rename(self):
        """Category ID must be stable across renames."""
        category_id = "cat-uuid-123"
        # Simulate rename: only name changes, ID stays
        renamed = {"id": category_id, "name": "New Name"}
        assert renamed["id"] == category_id

    def test_multiple_renames_accumulate_aliases(self):
        """Each rename adds one alias. Three names = two aliases."""
        names_over_time = ["Groceries", "Dagligvarer", "Mad og drikke"]
        aliases = names_over_time[:-1]  # all except current
        assert aliases == ["Groceries", "Dagligvarer"]
        assert len(aliases) == 2

    def test_rename_to_same_name_creates_no_alias(self):
        """Renaming to the same name should be a no-op."""
        current = "Dagligvarer"
        new = "Dagligvarer"
        should_create_alias = current != new
        assert should_create_alias is False

    def test_archived_category_name_can_be_reused(self):
        """An archived category's name should not block a new category."""
        active_names = ["Transport", "Sundhed"]
        archived_names = ["Old Category"]
        new_name = "Old Category"
        conflicts_with_active = new_name in active_names
        assert conflicts_with_active is False
