"""Service for household creation and settings management."""

from uuid import UUID

import asyncpg

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.repositories.household import HouseholdRepository


class HouseholdService:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def create_household(
        self,
        user_id: UUID,
        household_name: str,
        display_name: str,
    ) -> dict:
        """Create household + settings + owner member atomically."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                repo = HouseholdRepository(conn)

                existing = await repo.get_member_by_user(user_id)
                if existing is not None:
                    raise ConflictError("User already belongs to a household")

                household = await repo.create_household(household_name)
                try:
                    member = await repo.create_member(
                        household["id"], user_id, display_name, role="owner",
                    )
                except asyncpg.UniqueViolationError:
                    raise ConflictError("User already belongs to a household")

                settings = await repo.create_settings(household["id"])

                return {
                    "household": household,
                    "member": member,
                    "settings": settings,
                }

    async def get_my_household(self, household_id: UUID) -> dict:
        async with self.pool.acquire() as conn:
            repo = HouseholdRepository(conn)
            household = await repo.get_household(household_id)
            if not household:
                raise NotFoundError("Household not found")
            return household

    async def get_settings(self, household_id: UUID) -> dict:
        async with self.pool.acquire() as conn:
            repo = HouseholdRepository(conn)
            settings = await repo.get_settings(household_id)
            if not settings:
                raise NotFoundError("Household settings not found")
            return settings

    async def update_settings(
        self,
        household_id: UUID,
        fields_set: set[str],
        shift_late_income=...,
        late_income_cutoff_day=...,
    ) -> dict:
        """Update household settings with explicit-field semantics.

        Uses ``fields_set`` (from ``body.model_fields_set``) to distinguish
        omitted fields from explicit nulls. Validates the final state before
        writing to prevent the DB CHECK constraint from firing as a raw 500.
        """
        if not fields_set:
            raise ValidationError("At least one field must be provided")

        async with self.pool.acquire() as conn:
            repo = HouseholdRepository(conn)
            current = await repo.get_settings(household_id)
            if not current:
                raise NotFoundError("Household settings not found")

            # Compute final state by merging request with current DB values
            final_shift = (
                shift_late_income
                if "shift_late_income" in fields_set
                else current["shift_late_income"]
            )
            final_cutoff = (
                late_income_cutoff_day
                if "late_income_cutoff_day" in fields_set
                else current["late_income_cutoff_day"]
            )

            # Validate final state
            if final_shift and final_cutoff is None:
                if "late_income_cutoff_day" in fields_set:
                    raise ValidationError(
                        "Cannot clear late_income_cutoff_day while "
                        "shift_late_income is enabled"
                    )
                raise ValidationError(
                    "late_income_cutoff_day is required when "
                    "shift_late_income is enabled"
                )

            # Build repo kwargs: sentinel ... for fields not in fields_set
            repo_shift = (
                shift_late_income
                if "shift_late_income" in fields_set
                else ...
            )
            repo_cutoff = (
                late_income_cutoff_day
                if "late_income_cutoff_day" in fields_set
                else ...
            )

            updated = await repo.update_settings(
                household_id,
                shift_late_income=repo_shift,
                late_income_cutoff_day=repo_cutoff,
            )
            if not updated:
                raise NotFoundError("Household settings not found")
            return updated
