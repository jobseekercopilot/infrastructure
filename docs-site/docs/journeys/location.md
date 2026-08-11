# Location and commute

## Candidate location path

```mermaid
sequenceDiagram
  actor User
  participant UI as Angular profile UI
  participant BFF as Express BFF
  participant Gateway as Location Gateway
  participant Location as Location Service
  participant Google as Google Maps Gateway
  participant Postcode as Postcode.io Gateway

  User->>UI: Type a UK town or postcode
  UI->>BFF: POST /api/v2/locations/autocomplete
  BFF->>Gateway: Same-origin bounded request
  Gateway->>Location: Internal authenticated request
  alt Google enabled
    Location->>Google: Places autocomplete
    Google-->>Location: Transient suggestions + attribution
  else Google disabled/unavailable
    Location->>Postcode: Bounded place search
    Postcode-->>Location: Postcodes.io or fixture results
  end
  Location-->>UI: Opaque session, suggestions, provider attribution
  User->>UI: Select suggestion
  UI->>BFF: POST /api/v2/locations/resolve
  BFF->>Gateway: Opaque session/suggestion IDs
  Gateway->>Location: Resolve canonical location
  Location->>Postcode: Verify/canonicalise UK data where required
  Location-->>UI: Canonical location + provenance
```

Location Gateway is the public boundary. Location Service owns provider
selection, transient suggestion sessions, canonical resolution and provider-
neutral contracts. Google Maps Gateway alone receives the Google credential and
Google DTOs. Postcode.io Gateway remains the authority for persistable UK
postcode data and also backs the legacy bounded GET place/postcode routes.

The browser displays `Google Maps` attribution beside Google suggestions. A
Google Place ID can be retained as a provider reference where permitted, but
autocomplete labels, address components, coordinates and provider payloads are
not persisted as profile truth. User Profile owns the selected canonical
location and preferences.

## Advisory commute path

```mermaid
sequenceDiagram
  participant Job as Job Service
  participant Match as Job Matching Service
  participant Location as Location Service
  participant Google as Google Maps Gateway
  participant Routes as Google Routes API

  Job->>Match: Canonical jobs + home location/preferences
  Match->>Match: Select at most five eligible destinations
  Match->>Location: POST /internal/v1/commutes/matrix
  alt Google enabled and routeable
    Location->>Google: Provider-neutral matrix request
    Google->>Routes: Compute Route Matrix
    Routes-->>Google: Per-destination status/distance/duration
    Google-->>Location: Bounded attributed estimates
  else Disabled, unavailable, remote or insufficient precision
    Location-->>Match: Typed unavailable/not-applicable result
  end
  Match-->>Job: Jobs + application state + advisory commute metadata
```

Commute assessment supports drive and transit preferences, remains advisory,
and does not filter out a job. Route results are transient and are not written
to a profile, saved job or application. Partial provider failures degrade to a
typed unavailable state rather than invented distance or journey time.

## Modes and evidence

- Base and E2E profiles keep Google disabled and use deterministic Postcodes.io
  fixtures.
- `google-maps-smoke` enables only Google for a bounded live validation.
- `real-providers` enables Google alongside the real job-provider and OpenAI
  paths; Stripe remains fixture-backed.
- On 11 August 2026 the current manual stack returned five Google-attributed
  suggestions through the normal browser/BFF/gateway/service path. This proves
  integration, not provider reliability or production approval.

Privacy/terms notices, explicit enablement, server-only credentials, request
limits and provider attribution remain part of the activation boundary. See
the [configuration reference](../operations/configuration.md) and the operator
runbook in `docs/GOOGLE_MAPS_ACTIVATION.md`.
