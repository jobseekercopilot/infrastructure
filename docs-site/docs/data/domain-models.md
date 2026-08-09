# Domain models

These diagrams show useful ownership relationships, not every table or Java class.

## Account and profile

```mermaid
erDiagram
  AUTH_USER ||--o{ AUTHENTICATION_SESSION : has
  AUTHENTICATION_SESSION ||--o{ REFRESH_TOKEN : rotates
  AUTH_USER ||--o{ PASSWORD_RESET_TOKEN : requests
  AUTH_USER ||--o{ ACCOUNT_DELETION_OPERATION : initiates

  USER_PROFILE ||--o{ QUALIFICATION : contains
  USER_PROFILE ||--o{ ROLE : contains
  USER_PROFILE ||--o{ EVIDENCE_ENTRY : owns
  EVIDENCE_ENTRY ||--o{ EVIDENCE_REVISION : versions
  EVIDENCE_REVISION ||--o{ EVIDENCE_FACT : exposes
  USER_PROFILE ||--o{ EVIDENCE_SNAPSHOT : issues
  EVIDENCE_SNAPSHOT ||--o{ EVIDENCE_SNAPSHOT_SELECTION : selects
  EVIDENCE_SNAPSHOT_SELECTION ||--o{ EVIDENCE_SNAPSHOT_FACT : freezes
```

Authentication and profile records are in separate databases. Their shared subject identifier is an API-level identity, not a foreign key.

## Saved jobs, documents, and applications

```mermaid
erDiagram
  SAVED_JOB ||--o{ SAVED_JOB_SNAPSHOT : versions
  SAVED_JOB_SNAPSHOT ||..o{ GENERATION_OPERATION : referenced_by
  GENERATION_OPERATION ||..o{ GENERATED_DOCUMENT : creates
  DOCUMENT_FAMILY ||--o{ GENERATED_DOCUMENT : groups
  GENERATED_DOCUMENT ||--o{ EXPORTED_DOCUMENT_FILE : renders
  GENERATED_DOCUMENT ||--o{ DOCUMENT_LIFECYCLE_EVENT : records
  APPLICATION_RECORD ||--o{ APPLICATION_EVENT : records
  APPLICATION_RECORD ||..o| GENERATED_DOCUMENT : selects_cv
  APPLICATION_RECORD ||..o| GENERATED_DOCUMENT : selects_cover_letter
  APPLICATION_RECORD ||--o{ APPLICATION_DOCUMENT_WORKFLOW : coordinates
```

Dotted relationships cross an API/database boundary and are represented by immutable IDs, versions, hashes, and provenance—not relational foreign keys.

## Payment ledger

```mermaid
erDiagram
  AI_TOKEN_WALLET ||--o{ AI_TOKEN_TRANSACTION : records
  AI_TOKEN_WALLET ||--o{ AI_TOKEN_RESERVATION : holds
  GENERATION_OPERATION ||..o| AI_TOKEN_RESERVATION : idempotency_reference
```

Transactions are the append-only audit trail. Reservations isolate estimated usage from later commit/release and can be recovered after interrupted document-generation steps.

## Application lifecycle data

`application_records` holds the current lifecycle projection and optimistic version. `application_events` is the immutable activity history. Separate selection/applied command tables make exact retries idempotent. Workflow and reconciliation tables record progress when Document Store calls cannot complete within the request.

## Document lifecycle data

`generated_documents` represents immutable versions (with family and parent lineage); `exported_document_files` represents stored artifacts. Storage operation/cursor tables reconcile metadata and object-provider effects. Lifecycle/activity tables retain audit events, while tombstones preserve content-free relationships after an approved purge.

