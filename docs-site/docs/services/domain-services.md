# Domain services

## Authentication Service

Owns accounts, password hashes, login controls, sessions, refresh rotation/revocation, password-reset tokens, JWT signing/JWKS, and account lifecycle coordination. PostgreSQL with Flyway is mandatory outside tests.

## User Profile Service

Owns the claimant profile, search/commute preferences, structured evidence library and immutable purpose-bound evidence snapshots. Ownership comes from JWT `sub`; responses carry revision, revision ID, digest, and ETag.

## Job Service

Fans search out to Reed/Adzuna/JSearch, maps provider data to the canonical schema, enriches fields, deduplicates, sorts/pages, and optionally asks Job Matching for application state. Only saved-job snapshots are persisted.

## Job Matching Service

Stateless application-state reconciliation. It loads Application Tracker records and matches them to found jobs by stable identifiers or exact normalised fields. It does not calculate candidate suitability.

## Application Tracker Service

Owns application records, optimistic lifecycle transitions, apply-time document freezes, immutable events, and recoverable document workflows. PostgreSQL state is authoritative even when a cross-service operation remains pending.

## Document Store Service

Owns families, immutable generated document versions, file metadata and bytes, current/approval pointers, evidence lineage, lifecycle events, uploads, archive/recovery/purge controls, tombstones, and workflow journals. Local bytes use a filesystem volume; provider configuration can change the object store boundary.

## Document Export Service

Stateless renderer for DOCX/PDF and bounded DOCX upload ingestion. It reads/writes through Document Store APIs and never becomes a second document system of record.

## CV and Cover Letter Service

Builds minimal purpose-specific prompts, calls LLM Gateway, validates typed output and source claims, and returns draft content plus claim/model usage evidence. The durable API is side-effect-free for documents/applications; a legacy generate-and-commit endpoint remains during migration. An optional encrypted, short-lived rejected-output quarantine supports operator replay without a second model call.

## Reporting Service

Read-only projection over Application Tracker history, content-free Document Store activity, and current profile target hours. It owns no database and does not decide domain state.

## Payment Service

Owns document-credit wallets, append-only transactions, the reviewed catalogue,
immutable Checkout order snapshots, provider-event reconciliation, promotions
and recoverable document reservations. Caller-specific service identities
separate Payment Gateway, Stripe webhook fulfilment, account lifecycle and
Document Generation coordination.
