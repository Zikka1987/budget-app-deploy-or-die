# Documentation Index

This directory contains the high-level project documentation for the budget app.

## Document Purpose

### `../CLAUDE.md`
Project-wide rules and invariants.

Use this as the primary instruction file for:
- product constraints
- architecture boundaries
- workflow invariants
- non-goals

### `PRODUCT.md`
Product vision and intended behavior.

Use this for:
- what the app is supposed to be
- target user flows
- functional goals
- UX principles
- success criteria

### `../report.md`
Current implementation status and technical handoff.

Use this for:
- what is currently implemented
- what is stubbed or missing
- current architecture summary
- verification status
- next implementation priorities

### `../backend/CLAUDE.md`
Backend-specific engineering rules.

Use this for:
- backend layer responsibilities
- transaction rules
- repository/service boundaries
- backend testing expectations

### `../backend/app/api/v1/CLAUDE.md`
API router rules.

Use this for:
- thin-router expectations
- auth dependency usage
- route-level response/error behavior

## How to Use These Docs

- Use `CLAUDE.md` for rules and invariants.
- Use `PRODUCT.md` for intended product behavior.
- Use `report.md` for current implementation reality.
- If product intent and implementation status differ, follow `CLAUDE.md`, then check whether `report.md` needs updating.
- Do not use `report.md` as the source of product vision.

## Update Discipline

Update:
- `PRODUCT.md` when product intent changes
- `report.md` when implementation status or verification status changes
- `CLAUDE.md` files only when rules or invariants change