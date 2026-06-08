-- Bootstrap script for plain Postgres (non-Supabase) test environment.
-- Creates stub schemas and functions that the migration SQL references.
-- Run BEFORE applying any migration files.

-- Extension used by gen_random_uuid() in all tables
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ── auth schema (Supabase-managed in production) ──

CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE IF NOT EXISTS auth.users (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email      TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Stub: migrations define get_household_id() which calls auth.uid().
-- In tests we connect as superuser so RLS is bypassed, but the function
-- must exist for the CREATE FUNCTION statement to succeed.
CREATE OR REPLACE FUNCTION auth.uid()
RETURNS UUID
LANGUAGE sql
STABLE
AS $$ SELECT NULL::UUID $$;

-- ── storage schema (Supabase Storage in production) ──

CREATE SCHEMA IF NOT EXISTS storage;

CREATE TABLE IF NOT EXISTS storage.buckets (
    id                  TEXT PRIMARY KEY,
    name                TEXT,
    public              BOOLEAN,
    file_size_limit     INT,
    allowed_mime_types  TEXT[]
);

CREATE TABLE IF NOT EXISTS storage.objects (
    id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bucket_id TEXT,
    name      TEXT
);

-- Enable RLS on storage.objects so CREATE POLICY statements succeed.
ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;

-- Stub function referenced by storage RLS policies in migration 00001.
CREATE OR REPLACE FUNCTION storage.foldername(name TEXT)
RETURNS TEXT[]
LANGUAGE sql
AS $$ SELECT string_to_array(name, '/') $$;
