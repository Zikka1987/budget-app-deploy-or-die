#!/usr/bin/env bash
# Run the initial migration against a Postgres database.
# Usage: ./scripts/setup_db.sh <DATABASE_URL>
#
# Example:
#   ./scripts/setup_db.sh "postgresql://postgres:password@db.xxx.supabase.co:5432/postgres"

set -euo pipefail

DB_URL="${1:?Usage: setup_db.sh <DATABASE_URL>}"
MIGRATION_FILE="supabase/migrations/00001_initial_schema.sql"

if [ ! -f "$MIGRATION_FILE" ]; then
    echo "Error: Migration file not found at $MIGRATION_FILE"
    exit 1
fi

echo "Running migration: $MIGRATION_FILE"
psql "$DB_URL" -f "$MIGRATION_FILE"
echo "Migration complete."
