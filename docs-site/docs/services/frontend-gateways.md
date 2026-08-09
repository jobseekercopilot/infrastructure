# Frontend and gateways

## Client and BFF

Angular 21 renders the product UI; Express provides SSR and the same-origin API boundary. The BFF forwards a strict route allowlist, applies body/deadline/security-header policy, and translates HttpOnly session cookies into downstream credentials only in server memory. It owns no persistent user data.

Important routes include `/api/auth/**`, `/api/locations`, `/api/postcodes/**`, `/api/jobs/**`, `/api/v1/document-generation/**`, narrow `/api/v1/documents/**` reads/downloads, and `/api/v1/reports/**`. Payments are fail-closed.

## User Management Gateway

Coordinates registration/login/session cookies and exposes subject-bound profile/evidence operations. It calls Authentication Service using a service identity and User Profile Service using the claimant access token.

## Job Finder Gateway

Validates the JWT, derives the claimant subject, converts profile defaults into a search request when needed, and proxies saved-job/application operations to their owners. It owns no search or application data.

## Document Generation Gateway

Both a resource gateway and a durable coordinator. Its PostgreSQL operation record makes multi-service generation, approval, export, tracker linkage, and free application-document upload/linking replayable. It stores workflow references/checkpoints, not document bytes or application truth. The upload path sends PDF/DOCX bytes only to Document Store and deliberately bypasses Payment, generation, export, and LLM components.

## Reporting Gateway

Validates the claimant JWT and forwards the trusted subject, bearer token, and a dedicated service identity to Reporting Service. It exposes summary, UC-journal, and text evidence routes.

## Payment Gateway

Requires a trusted BFF service token plus owner header, then calls Payment Service or Stripe Gateway. The backend is implemented, but the BFF does not register payment routes on `develop`.

## Location Gateway

The current location orchestration layer. It validates and rate-limits place/postcode queries, adds cache/retry/circuit behaviour, and calls Postcode.io Gateway. It does not call the unimplemented Location Service.
