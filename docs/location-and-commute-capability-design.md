# Features 34 and 35: Location and commute capability design

Status: **Proposed — implementation requires explicit approval**  
Prepared: 9 August 2026  
Features: `document-generation-gateway#34`, `document-generation-gateway#35`  
Parent: `[Epic] Expand the Job Seeker Copilot Private Beta`

This report is research and design only. It does not authorise application code,
contract, schema, infrastructure, credential, matching-behaviour, or deployment
changes.

## Executive conclusion

Treat Features #34 and #35 as one capability with three layers. Retain the
existing frontend gateway and create two purpose-specific repositories:

- `location-gateway`: retained as the deliberately thin, frontend-facing API.
- `location-service`: provider-neutral location search orchestration, canonical
  location normalisation, and commute-matrix orchestration.
- `google-maps-gateway`: the only service that calls Google Places and Routes.

Move the current provider-neutral orchestration behaviour out of
`location-gateway` and into `location-service`, while preserving
`location-gateway` as the frontend boundary. The gateway should translate and
forward; it should not own provider selection, normalisation, or Google session
policy.
`postcode-io-gateway` remains the Postcodes.io provider adapter and remains the
source of persistable UK postcode enrichment for the beta.

Google data should be treated as display-time or calculation-time provider
content, not copied into permanent Job Seeker Copilot records. The beta should
persist an internal location identity, Google Place ID where permitted,
Postcodes.io-derived UK fields, user-confirmed fields, and field-level
provenance. It should not persist Google formatted addresses, address components,
coordinates, route durations, or route distances. Provider/legal and privacy
approval is a release gate because current Google terms impose material limits
on storage, combination with other data, and European end-user personal data.

For the beta, route only a bounded shortlist, support `DRIVE` and `TRANSIT`, use
a documented next-weekday 08:30 Europe/London departure, and expose commute as
an estimated advisory signal. Never remove a job solely because Google is
unavailable or the location is approximate.

# 1. Existing architecture

## 1.1 Repository evidence reviewed

The design was based on the following implementations, contracts, migrations,
tests, and architecture records rather than only the Feature descriptions:

- `location-gateway`: location controller/service/models, provider contract,
  location-search documentation, beta audit, LOC-02/LOC-05 merge history and
  tests.
- `postcode-io-gateway`: live/fixture adapters, place and postcode contracts,
  validation, caching/resilience behaviour, and tests.
- `user-profile-service`: profile entity, embedded location and work-preference
  models, OpenAPI contract, migrations V1–V4, validation and normalisation.
- `job-finder-gateway`: profile-default loading and job-search request mapping.
- `job-service`: provider adapters, canonical job model, location provenance,
  Haversine distance calculation, optional matching enrichment, saved-job
  snapshots, OpenAPI contract and tests.
- `job-matching-service`: MATCH-01 enrichment implementation, application
  matching rules, contract and tests.
- `job-seeker-copilot-client`: profile location UI, generated location client,
  legacy gateway wrapper, job request mapping, BFF configuration and frontend
  tests.
- `infrastructure`: ADR 0001 service ownership and ADR 0002 versioned contracts.
- Related local Git history for completed location and matching work.

GitHub's connected app had no installed account and the local `gh` credential
was invalid during this research. Remote Feature bodies, sub-issue state,
review threads, and Project fields therefore could not be verified or updated.
This is recorded as a planning-access blocker, not an application blocker.

## 1.2 Current responsibility map

| Responsibility | Current owner | Evidence/constraint |
| --- | --- | --- |
| Candidate location input | Angular client | Profile form says “Town or postcode” and stores the selected result. |
| Place/postcode facade | `location-gateway` | Exposes `/api/locations?q=` and `/api/postcodes/{postcode}`. |
| Postcodes.io provider access | `postcode-io-gateway` | Owns live/fixture provider calls, validation, deadlines, retry, circuit and metrics. |
| Stored home location and commute range | `user-profile-service` | Stores postcode, region, district, coordinates and `commuteRange` in miles. |
| Search orchestration | `job-finder-gateway` | Loads profile defaults and forwards a job-service request. |
| Canonical job/location normalisation | `job-service` | Provider adapters produce `CanonicalLocation`, provenance, workplace type and coordinates. |
| Straight-line distance | `job-service` | Haversine calculation populates `distanceMiles`. |
| Matching today | `job-matching-service` | Reconciles jobs with Application Tracker state; it does not yet calculate suitability. |
| Result presentation | Angular client | Shows job location and distance; no commute assessment exists. |

ADR 0001 explicitly places location acquisition/canonicalisation before job
search, job-provider normalisation and distance in `job-service`, orchestration
in `job-finder-gateway`, and matching enrichment in `job-matching-service`.

## 1.3 Current end-to-end flows

### Current user-location flow

```text
Profile form
  -> generated Location Gateway client
  -> search by place or lookup by postcode
  -> user selects a result
  -> client maps name/postcode/region/latitude/longitude
  -> user-profile-service persists PostcodeLocation
```

The client starts searching from two characters and uses `switchMap`, but does
not debounce or suppress duplicate input. Suggestions are buttons rather than a
complete ARIA combobox/listbox interaction, and arrow-key active-option
navigation is absent. If selection is bypassed, typed place text can be treated
as a postcode. The current manual fallback therefore needs clearer state.

### Current postcode lookup flow

```text
Client or location-gateway
  -> postcode-io-gateway
  -> Postcodes.io
  -> validated UK postcode/location response
  -> 15-minute bounded cache for successful postcode lookup
```

Place-name search is deliberately bounded to ten results and is not cached.
The Postcodes.io place dataset is sourced from Ordnance Survey Open Names and
covers Great Britain, not Northern Ireland.

### Current job-location flow

```text
Adzuna / JSearch / Reed gateway result
  -> job-service provider adapter
  -> Job.canonicalLocation + workplaceType
  -> optional Haversine distance
  -> optional application-state enrichment
  -> job-finder-gateway
  -> client
```

Adzuna and JSearch can supply coordinates. Reed commonly supplies only a label.
The canonical job model already distinguishes raw and normalised fields,
provider provenance, status and confidence, but provider adapters do not yet
produce a single reusable canonical contract shared with the profile domain.

### Current distance calculation

`job-service` uses a profile `HomeLocation` (or work-preference coordinates as a
fallback) and job coordinates in a Haversine calculation. This is straight-line
distance, not road or transit time. Search criteria use the first aspiration
location and a default provider radius; the profile's `commuteRange` is not
propagated end to end.

### Current matching flow

`job-matching-service` matches a found job to Application Tracker records by
canonical ID, provider/external ID, or normalised title/company/location. It
adds application metadata. It does not currently own a job-suitability score.
`job-service` treats matching as optional and preserves provider jobs on timeout
or failure. That degradation property must be retained.

### Current frontend location UX

The Angular client models loading, results, empty, invalid, rate-limited and
unavailable states. It resolves a saved postcode before search when coordinates
are missing. Gaps relevant to #34 are input debouncing, keyboard/listbox
semantics, selected-versus-unconfirmed state, explicit manual fallback, Google
attribution, and request/session lifecycle.

# 2. Key research findings

## 2.1 Google APIs

| API | Proposed purpose | Request/response facts | Authentication, billing and limits | Recommendation |
| --- | --- | --- | --- | --- |
| [Places API (New) Autocomplete](https://developers.google.com/maps/documentation/places/web-service/place-autocomplete) | Candidate-facing locality/postcode discovery | `POST /v1/places:autocomplete`; send `input`, session token, UK region restriction, `(regions)`/appropriate primary types and a response field mask; predictions include place ID and display text. | API key or OAuth; per-method quota; Autocomplete Requests SKU, with session pricing when correctly terminated; Google attribution required when shown without a map. | Use through `google-maps-gateway`; minimum 3 characters, 300 ms debounce, cancel stale requests, maximum five displayed suggestions. |
| [Place Details (New)](https://developers.google.com/maps/documentation/places/web-service/place-details) | Resolve the selected prediction | `GET /v1/places/{placeId}` with a required field mask. Essentials fields include address components, formatted address and location; `displayName` triggers a higher SKU. | Billed by highest field-mask SKU. IDs-only is free; Essentials and Pro have different caps/prices. | Request only fields approved by the data policy. Avoid `displayName` if the prediction label is sufficient for the active UI. Do not use provider payloads as a permanent canonical record. |
| [Geocoding API](https://developers.google.com/maps/documentation/geocoding/overview) | Convert free text/address to coordinates | Geocodes addresses and returns address components and geometry. | Separate Essentials SKU and quota. Same Maps content restrictions apply. | Not required for the beta. Do not bulk-geocode provider jobs. Reconsider only after provider approval and evidence that Places plus Postcodes.io cannot meet the need. |
| [Routes API Compute Route Matrix](https://developers.google.com/maps/documentation/routes/compute_route_matrix) | One candidate origin against several job destinations | `POST /distanceMatrix/v2:computeRouteMatrix`; origins × destinations form billable elements; request travel mode, time/routing options and field mask; response elements carry indexes, status/condition, duration and distance. | API key or OAuth and billing required. Matrix is billed per element. Current limits include 3,000 elements/minute and bounded elements/request; traffic-aware and transit combinations have lower request maxima than the basic case. | Use one origin and at most five shortlisted destinations per mode. Do not use legacy Distance Matrix. |
| [Routes API Compute Routes](https://developers.google.com/maps/documentation/routes/compute_routes) | One-off route detail | One origin/destination route with duration/distance and optional route detail. | Billed per request; fields/features determine Essentials/Pro/Enterprise SKU. | Not needed for list matching. Reserve for a future job-detail experience if required. |

Google documents `DRIVE`, `TRANSIT`, `WALK`, `BICYCLE` and `TWO_WHEELER`.
`WALK`, `BICYCLE` and `TWO_WHEELER` are currently beta modes and require a
specific warning because paths may be incomplete; only drive and transit should
be beta modes. See the [RouteTravelMode reference](https://developers.google.com/maps/documentation/routes/reference/rest/v2/RouteTravelMode).

Transit accepts departure or arrival time and is schedule-dependent. Driving
supports departure-time traffic options. Google describes `BEST_GUESS` as a
blend of historical and live traffic, with live conditions weighted more near
the present. Results are planning estimates, not guarantees. See
[transit routing](https://developers.google.com/maps/documentation/routes/transit-route)
and the [traffic model reference](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TrafficModel).

Google recommends Place IDs for durable provider identity. Place IDs may be
stored and should be refreshed if older than 12 months; an IDs-only details
refresh uses a no-charge SKU. Place IDs can become obsolete or be replaced, so
they are provider references rather than Job Seeker Copilot primary keys. See
[Place IDs](https://developers.google.com/maps/documentation/places/web-service/place-id).

## 2.2 Postcodes.io

[Postcodes.io place query](https://postcodes.io/docs/place/query/) provides
official place names, persistent OS identifiers in most cases, outcodes,
administrative areas and approximate coordinates from Ordnance Survey Open
Names. Its place coverage is Great Britain. Postcode lookup provides the richer
UK-specific postcode and administrative data already consumed by the platform.

Its continuing value is:

- an existing isolated provider boundary and tested resilience path;
- UK postcode validation and normalisation;
- persistable, provenance-labelled UK data under its applicable data licences;
- no Google billing or Google credential dependency for the existing path;
- a degradation path when Google is unavailable.

It cannot by itself provide Google-level autocomplete coverage or route times.

## 2.3 Provider/legal/data-usage findings

This is a technical reading of published terms, not legal advice. The account's
billing country and negotiated terms must be confirmed before implementation.

### Clearly permitted by published documentation

- Places and Routes content may be used in an application without displaying a
  Google map, subject to attribution and other terms.
- Google IDs such as Place IDs may be retained where the service documentation
  allows it.
- Places latitude/longitude and Routes latitude/longitude may be cached for up
  to 30 consecutive calendar days, then deleted.
- Google attribution can be shown beside results without embedding a map.

Sources: [Maps service-specific terms](https://cloud.google.com/maps-platform/terms/maps-service-terms),
[Places policies](https://developers.google.com/maps/documentation/places/web-service/policies),
and [Routes policies](https://developers.google.com/maps/documentation/routes/policies).

### Apparently permitted subject to conditions

- Autocomplete predictions and route estimates may be displayed in the product
  when required attribution is adjacent to clearly distinguished Google content.
- A user-selected, fully and accurately user-supplied address has a documented
  exception in Places policies, but applying that exception to broad localities
  such as “London” or “Uxbridge” is not sufficiently clear for this design to
  rely on it.
- End-user location can be obtained/cached only after advance notice and
  express, prior, revocable consent.

### Requires provider/legal or privacy confirmation

- Whether sending a UK candidate's selected postcode centroid to Routes through
  a server complies with the restriction on the customer providing a European
  end user's personal data to Google.
- Whether using a transient Google-derived postcode as a lookup key for
  Postcodes.io is an allowed provider-combination workflow.
- Whether an advisory commute assessment in an employment product is an allowed
  derived use of Routes content. The current AUP prohibits limiting sensitive
  opportunities based on demographics; this design does not use demographics,
  but written use-case confirmation is prudent.
- Whether any negotiated or EEA-specific terms apply, based on the billing
  address rather than the user's location.
- Whether route duration/distance can be cached at all. Current Routes-specific
  terms explicitly permit only route latitude/longitude caching for 30 days;
  the general terms prohibit caching unless specifically allowed.

### Should not be stored in the proposed beta

- Google formatted addresses, autocomplete labels, address components,
  postcodes, locality/admin-area strings, or other Places content as permanent
  canonical fields.
- Google Places or Routes coordinates beyond an approved transient use.
- Route duration, distance, arrival/departure time, or provider response payloads
  in a database, event, analytics store, log, or saved-job snapshot.
- Bulk Google geocodes or an index assembled from Google content.

The [Google Maps Platform terms](https://cloud.google.com/maps-platform/terms)
prohibit prefetching/indexing/storing Maps content except where expressly
permitted, prohibit creating content from Maps content, and impose end-user
privacy requirements. They also state that Google receives search terms, IP
addresses and coordinates. The product Terms and Privacy Policy must identify
Google Maps features, Google's end-user terms and Privacy Policy.

## 2.4 Cost and quota constraints

Current global list pricing is pay-as-you-go per SKU and per calendar-month
event volume. As of 31 July 2026, the published first paid tier is:

- Autocomplete Requests: 10,000 monthly free events, then $2.83/1,000.
- Place Details Essentials: 10,000 free, then $5/1,000.
- Place Details Pro: 5,000 free, then $17/1,000.
- Compute Route Matrix Essentials: 10,000 free elements, then $5/1,000.
- Compute Route Matrix Pro: 5,000 free elements, then $10/1,000.

See the [current pricing table](https://developers.google.com/maps/billing-and-pricing/pricing).
Field masks and routing features determine the SKU. Matrix batching reduces
network round trips but not billable elements. Traffic-aware driving is a Pro
cost driver; an origin × five destinations produces five elements for each
mode.

# 3. Decisions

| Decision | Recommendation | Reason |
| --- | --- | --- |
| Places API | Places API (New) Autocomplete plus narrowly masked Place Details | Modern supported API, session lifecycle, strong user search; avoids legacy APIs. |
| Routing API | Routes API Compute Route Matrix | Designed for one-to-many comparison and replaces legacy Distance Matrix. |
| Repository boundaries | Retain thin `location-gateway`; add `location-service` and `google-maps-gateway` | Preserves the “frontend connects only to gateways” convention while separating edge API, domain policy and provider integration. |
| Postcodes.io role | Retain as UK postcode authority/enrichment and fallback | Existing tested integration, useful UK metadata, lower provider lock-in and safer persistent data. |
| Canonical ownership | `location-service` owns contract/normalisation rules; profile and job services own their records | One representation and provenance policy without centralising all domain persistence. |
| Google data persistence | Persist provider Place ID only until written approval expands the set | Google's general storage restrictions are narrower than Feature #34's proposed outcome. |
| Coordinate persistence | Persist Postcodes.io, user-supplied or job-provider coordinates with provenance; keep Google coordinates transient | Meets current use cases while avoiding indefinite Google-content storage and false precision. |
| Provider calls | Backend only through `google-maps-gateway` | Keeps credentials secret and centralises rate limits, cost metrics, redaction and fixtures. |
| Travel modes | Drive and transit for beta | Useful and generally available; walking/cycling are Google beta modes with mandatory warnings. |
| Commute time | Next working day, 08:30 Europe/London departure, clearly labelled estimate | Reproducible across modes and more representative than “now”; job start times are not reliably present. |
| Traffic | `DRIVE` with `TRAFFIC_AWARE`/`BEST_GUESS`; scheduled `TRANSIT` | Useful commute quality, explicitly budgeted as Pro for driving. |
| Filter/score/advisory | Advisory only in beta; remote compatibility remains explicit | Prevents false negatives while precision, availability and user trust are being evaluated. |
| Route candidate selection | Current result page, at most five eligible destinations per evaluation, after cheap checks | Bounded latency and cost. Not evaluated must not mean unsuitable. |
| Caching | No route-result cache for beta; only request coalescing without retaining results after the response completes | Current published permission does not clearly include duration/distance caching. |
| Fallback | Existing Postcodes.io search/manual postcode, Haversine distance and unmodified job results | External failure cannot break core search. |
| Privacy | Store postcode/outcode centroid rather than exact home address/rooftop coordinates; require revocable consent | Data minimisation and Google end-user location requirements. |
| Beta scope | UK only, one origin, one primary job destination, two modes, advisory explanation | Smallest useful design with bounded ambiguity and provider spend. |

# 4. Proposed architecture

## 4.1 Target topology

```text
Angular client
        |
        | candidate-facing API only
        v
+----------------------+
|   location-gateway   |  thin edge adapter; no provider/domain policy
+----------+-----------+
           |
           v
+----------------------+       +-----------------------+
|   location-service   |------>|  google-maps-gateway  |----> Places API (New)
| orchestration +      |       | provider DTOs, auth,  |
| canonical rules      |       | quotas, redaction     |----> Routes API
+----------+-----------+       +-----------------------+
           |
           +------------------>| postcode-io-gateway   |----> Postcodes.io
           |
           v
  Canonical Location contract
       /                 \
      v                   v
user-profile-service    job-service
  origin + prefs        provider jobs + Haversine prefilter
      \                   /
       \                 /
        v               v
          job-matching-service
          | eligibility and shortlist
          | commute request
          v
          location-service
          -> google-maps-gateway -> Compute Route Matrix
          <- transient route elements
          v
          CommuteAssessment + explanation codes
          v
job-service -> job-finder-gateway -> Angular client
```

The frontend connects only to `location-gateway`; it never connects to a domain
service or provider gateway. No browser or domain service calls Google directly.
No Google DTO crosses `google-maps-gateway`. `location-service` presents
provider-neutral contracts and owns fallback/orchestration. The matching service
owns the interpretation of a commute estimate against a candidate's preference.

## 4.2 Refactoring `location-gateway` into a thin edge

The existing `location-gateway` currently contains provider-neutral
orchestration over `postcode-io-gateway`. The target keeps the repository and
its candidate-facing responsibility, but moves domain work behind it.

Recommended staged cutover:

1. Create `location-service` with internal provider-neutral contracts and move
   normalisation, provider selection, fallback and commute orchestration into it.
2. Keep `location-gateway`'s existing public endpoints and generated frontend
   contract stable; change its implementation to call `location-service`.
3. Preserve edge concerns in the gateway: candidate authentication/authorisation,
   public DTO validation/mapping, request IDs, response shaping and edge rate
   limits.
4. Remove provider clients, provider selection, canonicalisation rules and
   provider credentials from `location-gateway` after parity tests pass.
5. Introduce public v2 endpoints in `location-gateway` and internal v1 endpoints
   in `location-service` behind disabled feature flags.
6. Observe v1 parity and rollback signals for a full beta release window before
   removing duplicated transitional code.

The invariant is a thin frontend gateway and exactly one provider-neutral domain
owner. `location-gateway` is not retired.

## 4.3 Feature dependency

```text
#34a provider/legal approval
        +
#34b thin location-gateway + location-service + google-maps-gateway boundaries
        +
#34c canonical Location v2 and provenance
        |
        +------------------------------+
        v                              v
#34d profile/job adoption       independent #35 work
        |                       - preference contract/UI
        |                       - fixture-based Routes adapter
        |                       - assessment rules/tests
        +---------------+--------------+
                        v
              #35 integrated route evaluation
                        v
              advisory explanation in results
```

Feature #35 depends on the canonical contract and provider/privacy decision in
#34. It must not duplicate normalisation in `job-matching-service`. Preference
UI/contracts, fixture-based Google gateway work, pure assessment rules and
observability definitions can proceed in parallel, but live integration cannot
be enabled until #34's location identity, precision and provenance are stable.

## 4.4 Responsibility ownership

| Responsibility | Owner |
| --- | --- |
| Google Places and Routes HTTP/auth/provider DTOs | `google-maps-gateway` |
| Postcodes.io HTTP/provider DTOs | `postcode-io-gateway` |
| Candidate-facing location API, edge authentication/validation and response mapping | `location-gateway` |
| Search orchestration, canonical model/rules, provider selection, route orchestration | `location-service` |
| Candidate origin and commute preferences | `user-profile-service` |
| Provider job normalisation, canonical job location, straight-line distance, saved job | `job-service` |
| Search/profile orchestration | `job-finder-gateway` |
| Commute eligibility, threshold comparison, explanation code, future score component | `job-matching-service` |
| Accessible search and explanation display | `job-seeker-copilot-client` |
| Secrets, service identity, egress, quotas, alerts | `infrastructure` |

# 5. Canonical data models

The following are logical contracts, not implementation-language declarations.
Fields marked transient must not be persisted.

## 5.1 Canonical Location v2

```yaml
Location:
  locationId: uuid                 # JSC identity, never a provider ID
  displayName: string              # JSC/user-confirmed or approved non-Google value
  countryCode: string              # ISO 3166-1 alpha-2; GB in beta
  postcode: string?                # approved canonical source only
  locality: string?
  region: string?
  latitude: decimal?               # persist only from approved non-Google source
  longitude: decimal?
  locationType: POSTCODE | LOCALITY | ADDRESS | WORKPLACE | REMOTE | UNKNOWN
  precision: EXACT_ADDRESS | POSTCODE_CENTROID | LOCALITY_CENTROID |
             PROVIDER_COORDINATE | NONE
  confidence: VERIFIED | PROVIDED | INFERRED | AMBIGUOUS | UNKNOWN
  providerReferences:
    - provider: GOOGLE_PLACES | POSTCODES_IO | JOB_PROVIDER | USER | LEGACY
      externalId: string?
      observedAt: instant
  fieldProvenance:
    - field: POSTCODE | LOCALITY | REGION | COORDINATES | DISPLAY_NAME
      source: GOOGLE_PLACES | POSTCODES_IO | JOB_PROVIDER | USER | LEGACY
      method: DIRECT | USER_CONFIRMED | LOOKUP_VERIFIED | INFERRED
      observedAt: instant
      confidence: VERIFIED | PROVIDED | INFERRED | AMBIGUOUS | UNKNOWN
  normalisedAt: instant
```

Important rules:

- `locationId` is stable inside Job Seeker Copilot; Google Place ID and OS place
  code are provider references.
- A persisted field has one stated source. A later provider observation does not
  silently overwrite it; normalisation creates a new provenance record/version.
- `PROVIDER_COORDINATE` does not claim address-level precision.
- A remote job has `locationType: REMOTE`, no synthetic coordinates, and an
  explicit workplace type in the job model.
- The beta does not need full address lines or county fields. Add them only for a
  proven product requirement and approved provider source.
- Transient Google suggestion text/address components may be shown with
  attribution during selection but are not part of the persisted contract.

### Ambiguity rules

| Input | Behaviour |
| --- | --- |
| `Uxbridge`, `Cambridge`, `Manchester`, `Paddington` | Require candidate selection from disambiguated results; persist only after provider-safe resolution. |
| `London` | Accept as `LOCALITY_CENTROID`, `AMBIGUOUS`; never represent as an exact workplace. |
| `UB3` | Normalise as `POSTCODE_CENTROID`/outcode; route suitability is approximate. |
| `Heathrow` | Preserve locality/POI ambiguity unless a precise workplace is provider-supplied and approved. |
| `remote` | Workplace semantics, not a geocode. No route request. |
| `London / hybrid` | Separate canonical location from `HYBRID`; do not parse both into a label. |
| `Multiple locations` | Beta uses provider-designated primary only and says so; nearest-office evaluation is post-beta. |
| `Nationwide`, `Various sites`, malformed values | `UNKNOWN`/`NONE`; route unavailable; retain raw provider text for display/provenance. |

## 5.2 Commute preferences

```yaml
CommutePreferences:
  enabledModes: [DRIVE | TRANSIT]
  maximumMinutes:
    DRIVE: integer?                # 5..180
    TRANSIT: integer?              # 5..180
  maximumDistanceMiles: integer?   # existing commuteRange compatibility
  referenceTimePolicy: NEXT_WORKDAY_0830_DEPARTURE  # system policy, read-only
```

The existing `workplaceArrangements` remains the source for `ONSITE`, `HYBRID`
and `REMOTE` preference. Do not add duplicate remote booleans. Store duration
only for an enabled mode. Walking/cycling fields wait until those modes enter
scope.

## 5.3 CommuteAssessment

```yaml
CommuteAssessment:
  status: WITHIN_PREFERENCE | ABOVE_PREFERENCE | UNAVAILABLE | NOT_APPLICABLE |
          NOT_EVALUATED
  workplaceType: ONSITE | HYBRID | REMOTE | UNKNOWN
  modes:
    - mode: DRIVE | TRANSIT
      estimateStatus: ESTIMATED | APPROXIMATE | UNAVAILABLE
      durationMinutes: integer?    # transient Google content
      distanceMiles: decimal?      # transient Google content
      thresholdMinutes: integer?
      outcome: WITHIN | ABOVE | NO_PREFERENCE | UNAVAILABLE
      calculatedFor: instant?
      calculatedAt: instant?
      originPrecision: enum
      destinationPrecision: enum
      reasonCode: string?
  bestSuitableMode: DRIVE | TRANSIT | null
  explanationCode: string
  explanationParameters: object   # transient, minimal
  providerAttribution: GOOGLE_MAPS | null
```

Never use `CONFIRMED` for a route estimate. The UI renders approved explanation
templates, for example:

- “Estimated drive: 32 minutes — within your preferred 45 minutes.”
- “Estimated public transport commute: 71 minutes — above your preferred 60 minutes.”
- “Commute could not be calculated because the workplace location is approximate.”
- “Hybrid role: commute estimate applies on office days.”

The assessment is response-only. The matching service may emit it and a future
versioned score component, but the beta does not persist it or hard-filter on it.

# 6. API changes

## 6.1 Location search and resolution

| Method/path | Owner | Request | Response | Errors/authentication | Why |
| --- | --- | --- | --- | --- | --- |
| `POST /api/v2/locations/autocomplete` | `location-gateway` | `{input, sessionId?, countryCodes:["GB"]}` | `{sessionId, suggestions:[{suggestionId, primaryText, secondaryText, precisionHint}], attribution}`; Google content is transient | 400 invalid, 429 budget/quota, 503 disabled/unavailable, 504 timeout; candidate auth at the gateway | Frontend-only gateway boundary, avoids search text in URL/access logs, supports attribution. |
| `POST /api/v2/locations/resolve` | `location-gateway` | `{sessionId, suggestionId}` | `{location, resolutionStatus, attribution}` or a request for explicit postcode confirmation | 400 invalid/stale, 404 unknown, 409 `CONFIRMATION_REQUIRED`, provider failures as above; candidate auth | Thin public endpoint over the location-service resolution use case. |
| `GET /api/postcodes/{postcode}` | `location-gateway` | Existing path parameter | Existing compatible response initially | Existing behaviour/auth | Preserve the frontend contract and reliable manual/postcode fallback. |

Suggestion IDs should be short-lived opaque references held in memory for the
active request/session; they must not embed raw provider payloads. A session
expires after selection, explicit clear, or a short idle period.
`location-gateway` passes the opaque session reference; `location-service` owns
the provider-neutral session lifecycle, and `google-maps-gateway` creates and
forwards the actual Google session token.

## 6.2 Internal location domain API

| Method/path | Owner | Request/response | Errors/authentication | Why |
| --- | --- | --- | --- | --- |
| `POST /internal/v1/locations/autocomplete` | `location-service` | Validated search intent/session reference -> provider-neutral suggestions and attribution metadata | Service auth; typed 400/429/502/503/504 | Gives the thin gateway one use-case endpoint while keeping provider selection/session policy in the service. |
| `POST /internal/v1/locations/resolve` | `location-service` | Opaque suggestion/session -> canonical Location or confirmation requirement | Service auth; typed 400/404/409/provider failures | Owns resolution, provenance and optional Postcodes.io verification. |
| `GET /internal/v1/postcodes/{postcode}` | `location-service` | Normalised postcode -> canonical location | Service auth; existing typed failures | Keeps Postcodes.io use and canonicalisation out of the frontend gateway. |

## 6.3 Internal Google provider API

| Method/path | Owner | Request/response | Errors/authentication | Why |
| --- | --- | --- | --- | --- |
| `POST /internal/v1/places/autocomplete` | `google-maps-gateway` | Provider-neutral bounded input -> prediction references/text/attribution | Service token or mTLS; 400, 429, 502/503/504; never expose Google key | Central provider adapter and field mask. |
| `POST /internal/v1/places/resolve` | `google-maps-gateway` | Place ID + session token -> narrowly masked transient place details | Same | Keeps Google DTO and session billing inside provider boundary. |
| `POST /internal/v1/routes/matrix` | `google-maps-gateway` | One origin, <=5 destinations, one mode/time policy -> per-element status/duration/distance | Same; partial elements returned with individual status | Central route auth, quota, field masks and pricing classification. |

`location-service` is the only consumer initially. Domain services do not learn
Google endpoints or request fields.

## 6.4 Commute orchestration and matching

| Method/path | Owner | Request | Response | Errors/authentication | Why |
| --- | --- | --- | --- | --- | --- |
| `POST /internal/v1/commutes/matrix` | `location-service` | Canonical origin, bounded canonical destinations, modes and reference-time policy | Provider-neutral transient estimates with precision and per-element status | Service auth; 400 invalid, 422 unroutable, 429, 502/503/504; partial success | Validates precision, groups/batches modes, calls Google gateway and preserves provider isolation. |
| `POST /api/v1/job-matches/enrich` (versioned extension) | `job-matching-service` | Existing user/jobs plus canonical origin and commute preferences | Existing application enrichment plus `CommuteAssessment` | Existing service auth; route failure becomes partial enrichment, not request failure | Reuses the existing optional matching boundary and adds suitability interpretation. |
| `POST /api/jobs/search` (versioned extension) | `job-finder-gateway`/`job-service` | Canonical origin and commute preferences propagated from profile or request | Jobs may include response-only commute assessment | Existing candidate/service auth | Carries the data end to end without profile calls from matching. |

All contracts remain producer-owned, versioned and generated per ADR 0002.
Consumers must support the old response during rollout. `job-service`'s matching
overlay must explicitly permit only matching-owned commute fields and continue
to preserve jobs when the matching call fails.

# 7. Persistence and migration

## 7.1 Persisted candidate data

Add nullable fields in `user-profile-service` only after approval:

| Field | Why permanently store it? |
| --- | --- |
| `location_id` | Stable JSC identity across edits/contracts without using a provider ID as a primary key. |
| `country_code` | Validates UK-beta scope and future-proofs without storing an address. |
| `location_type`, `precision`, `confidence` | Prevents approximate data being treated as exact and governs route eligibility. |
| Google Place ID provider reference | Re-resolve/refresh the selected provider identity without storing Google place content, subject to approval. |
| Postcodes.io/legacy source references | Auditable source and safe re-normalisation. |
| Field provenance | Explains where postcode, label and coordinates came from. A compact JSON/document column is acceptable because it is bounded and versioned. |
| `maximum_drive_minutes`, `maximum_transit_minutes`, enabled modes | Reuse across searches; these are explicit candidate preferences. |

Keep existing postcode, region, district and latitude/longitude when their source
is Postcodes.io or legacy Postcodes.io. Rename semantics/documentation so those
coordinates are understood as postcode/place centroids, not exact home
coordinates. Retain `commuteRange` for compatibility; do not silently convert
miles to minutes.

Do not persist Google autocomplete text, formatted address, address components,
locality/admin values or Google coordinates in beta.

## 7.2 Job and route persistence

- General search jobs remain transient. `job-service` continues to own safe
  provider-supplied canonical location/provenance.
- Saved-job snapshots may store provider/Postcodes.io/user-safe canonical
  location fields and provider references. They must omit commute assessment and
  transient Google content.
- Do not create a routing-results table, distributed cache, event stream or
  analytics copy. Recalculate an assessment when needed.
- Logs/traces contain status, mode, element counts and coarse precision only.

## 7.3 Existing-data migration

Use a compatibility adapter plus lazy migration:

1. Read every existing `PostcodeLocation` as a Location v2 with provider
   `LEGACY`/`POSTCODES_IO`, `POSTCODE_CENTROID` precision and existing values.
2. Add new columns nullable and dual-read, without a bulk Google call.
3. Write v2 provenance the next time the candidate explicitly edits/saves their
   location; no forced re-entry.
4. Run an idempotent background backfill only for internal IDs and deterministic
   provenance if operational reporting needs it. Do not call Google.
5. Keep old contract fields populated through the compatibility period.
6. Remove legacy fields only in a separately approved later migration after all
   consumers and rollback windows close.

Existing jobs require no database backfill because search results are transient.
Saved snapshots stay readable through version-aware deserialisation.

# 8. Cost and quota analysis

These estimates are planning illustrations in USD, not guaranteed bills. They
use the published global prices cited in section 2 and exclude tax, negotiated
discounts, retries, live smoke tests and abuse.

## 8.1 Assumptions

- 20 active days per user/month.
- 0.2 location-edit/search sessions per active user/day.
- 5 Autocomplete requests/session after a 3-character minimum and 300 ms debounce.
- 1 Essentials Place Details selection/session.
- 20 jobs shown/searched per user/day.
- Cheap eligibility and straight-line checks reduce route evaluation to 5 jobs.
- Both drive and transit enabled for the conservative model: 10 route matrix
  elements/user/day.
- Drive uses Pro traffic-aware matrix; transit uses Essentials matrix.
- 0% cross-request cache hit rate because route results are not cached.
- One matrix request per mode can batch the five destinations, but billing is
  still ten elements.

## 8.2 Volume and indicative spend

| Cohort | User-days/month | Autocomplete requests | Details | Drive Pro elements | Transit Essentials elements | Approximate list-price monthly cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Small beta: 10 active users | 200 | 200 | 40 | 1,000 | 1,000 | ~$0 within current monthly free caps |
| Medium beta: 100 | 2,000 | 2,000 | 400 | 10,000 | 10,000 | ~$50 (5,000 paid Drive Pro elements) |
| Early production: 1,000 | 20,000 | 20,000 | 4,000 | 100,000 | 100,000 | ~$1,428.30 |

The early-production arithmetic is approximately:

- Autocomplete: `(20,000 - 10,000) / 1,000 × $2.83 = $28.30`.
- Details Essentials: within 10,000 free events.
- Drive Pro matrix: `(100,000 - 5,000) / 1,000 × $10 = $950`.
- Transit Essentials matrix: `(100,000 - 10,000) / 1,000 × $5 = $450`.

The dominant cost is route matrix elements, especially traffic-aware driving.
If only half of users enable a mode, actual elements decrease correspondingly.

## 8.3 Controls

- Three-character minimum, 300 ms debounce, duplicate suppression and
  cancellation of stale autocomplete calls.
- Correct Google session tokens and selection termination.
- Narrow field masks; avoid Place Details Pro fields.
- One route evaluation per displayed result set, not per keystroke or sort.
- Remote/unknown/invalid-location exclusion before routing.
- Haversine/precision eligibility before routing, with at most five destinations.
- Matrix batching by mode.
- Per-candidate daily route-element budget and global daily quota ceiling.
- Separate dev/test/prod projects or keys and deliberately tiny non-production
  quotas.
- Cost dashboards and alerts at 50%, 75%, 90% and 100% of monthly budget.
- No automatic retry of billable successful elements; bounded retry only for
  documented transient failures and within the same user request budget.

# 9. Failure and degradation behaviour

| Failure | User-visible/result behaviour | System behaviour |
| --- | --- | --- |
| Google Places unavailable/timeout | Explain that enhanced search is unavailable; offer postcode/manual fallback; preserve current selected location | Circuit opens; Postcodes.io path remains available; no profile field is cleared. |
| Google quota exceeded | Same fallback, rate-limit message if user budget exhausted | Return typed 429/503 reason; alert on quota metric. |
| Invalid Google credentials | Enhanced functions disabled; core search continues | Readiness reports provider disabled; page operations do not repeatedly call provider; urgent alert. |
| Ambiguous/no-postcode selection | Ask user to select a more precise result or confirm a postcode; locality-only may be saved as approximate if allowed | Do not invent postcode/coordinates. |
| Malformed candidate location | Commute unavailable; profile edit prompt | Existing search text/provider criteria can still run. |
| Incomplete/approximate job location | Show raw job location and “commute unavailable/approximate” | Do not geocode silently; do not route if precision policy rejects it. |
| Routes timeout/quota/provider failure | Jobs remain; distance may remain; commute says temporarily unavailable | Optional matching status is partial; core job-search response succeeds. |
| Zero route/transit unavailable | Other mode can still succeed; explain no route for that mode | Preserve per-element status; do not fail the whole matrix. |
| Matching service unavailable | Existing provider jobs remain without commute/app enrichment | Retain current `OptionalJobMatchingEnricher` degradation. |
| Partial matrix response | Show only successful mode estimates and label unavailable modes | Never reuse indexes without validating origin/destination indexes and element status. |

No failure converts `NOT_EVALUATED` or `UNAVAILABLE` into `ABOVE_PREFERENCE`.

# 10. Security and privacy implications

## 10.1 Credentials and network boundary

- No browser Google web-service key. The Angular client calls only the
  authenticated `location-gateway` API.
- `google-maps-gateway` alone receives Google credentials.
- Prefer OAuth 2.0 workload identity for server-to-server APIs where supported.
  For beta API keys, use separate Places and Routes keys, restrict each to only
  its API, and restrict server source IP/CIDR if stable egress exists.
- Store secrets in the existing AWS secret-management path, inject at runtime,
  never commit or expose them in environment endpoints, client bundles, logs or
  error responses.
- Separate production and non-production Google projects/credentials/quotas.
- Rotate with overlapping old/new secrets, canary health check, then revoke;
  audit access and document an emergency abuse/revocation runbook.
- Authenticate service-to-service calls with the existing platform mechanism;
  candidates must never call an `/internal` endpoint.

Google's [security guidance](https://developers.google.com/maps/api-security-best-practices)
recommends API/application restrictions, separate keys, secure server-side
storage, IP restrictions for server web-service keys, and OAuth for supported
server-to-server use.

## 10.2 Data minimisation and consent

- Do not request browser geolocation; it is unnecessary for the beta and the
  current Permissions Policy already disables it.
- Ask the candidate to select a commute origin and explain that an approximate
  area/postcode and preferences will be sent to Google to estimate routes.
- Obtain express, prior, revocable consent before the first Google location or
  route request. Store the consent record/version, not Google content.
- Prefer a postcode/outcode or locality centroid over an address/rooftop point.
- Never send user ID, name, email, profile ID, job-application state or other
  identifiers to Google. Use only the minimum route coordinates/place reference.
- Profile deletion/export and retention processes must include canonical
  location, provider reference, preferences and consent record.
- Update the product Privacy Policy and Terms before enabling Google. Explain
  Google data collection, provider combination, purpose, retention, revocation,
  and the linked Google terms/privacy notice.
- Conduct a DPIA/privacy review because location plus employment preference is
  personal data, even when the stored coordinate is approximate.

Provider/privacy approval must resolve the European personal-data clause before
live route calls. If it cannot be approved, #34 may still ship with a compliant
search/display pattern, while #35 remains on Postcodes.io/Haversine advisory or
uses a different approved routing provider.

# 11. Testing strategy

## 11.1 Unit tests

- Field-level canonicalisation and deterministic provenance.
- Place ID versus internal ID rules.
- Precision/confidence transitions; no locality promoted to address precision.
- Remote/hybrid/onsite/unknown and malformed/multiple-location eligibility.
- Commute threshold boundary (`duration == maximum` is within).
- `UNAVAILABLE`, `NOT_EVALUATED` and `NOT_APPLICABLE` never treated as failure.
- Next-working-day/time-zone calculation including weekends and BST/GMT changes.
- Candidate-budget and five-destination cap.
- Redaction/no sensitive fields in structured logs.

## 11.2 Contract/provider adapter tests

- Checked-in Google Autocomplete, Details and Matrix fixtures for success,
  empty, ambiguous, partial, zero-route, 400, 401/403, 429, 5xx and timeout.
- Field-mask tests that fail if unapproved/Pro fields are requested.
- Matrix origin/destination index and per-element status handling.
- Postcodes.io existing live/fixture contracts retained.
- Producer-owned OpenAPI compatibility tests for v1 and v2 consumers.
- A policy test/architectural rule prevents Google provider DTOs outside
  `google-maps-gateway` and prevents persistence of transient commute fields.

## 11.3 Integration tests

- Google suggestion -> resolve -> Postcodes.io verified canonical location ->
  profile persistence with safe provenance.
- Legacy profile -> compatibility Location v2 -> search without edit.
- Profile origin/preferences -> job shortlist -> fixture matrix -> matching
  assessment -> job-service overlay.
- Provider route failure -> job result preserved with distance/fallback.
- Remote job -> no route provider invocation.

## 11.4 Frontend tests

- Debounce, minimum characters, duplicate suppression and stale cancellation.
- ARIA combobox/listbox roles, labelled input, arrow keys, Home/End where
  applicable, Enter selection, Escape close, focus return and screen-reader
  status announcements.
- Loading, no-results, rate-limited, provider-unavailable and manual fallback.
- Selected location chip/summary, edit/remove, and unconfirmed text cannot save
  as a postcode.
- Google attribution placement/contrast and separation from Postcodes.io/JSC data.
- Commute explanation language for estimated/approximate/unavailable states.

## 11.5 End-to-end scenarios

- Hayes candidate -> Uxbridge job -> drive enabled and within preference.
- Hayes -> Central London -> transit enabled with schedule-dependent estimate.
- London -> remote job -> commute not applicable and no route call.
- Existing postcode-only candidate -> approximate locality-only job -> no false precision.
- Hybrid job -> estimate explicitly applies to office days.
- Routing provider unavailable -> jobs and Haversine distance still displayed.
- Both modes enabled -> partial transit failure, successful drive retained.

Normal CI uses WireMock/fixtures and must never depend on paid Google services.
An opt-in, separately governed smoke suite may use synthetic public locations,
a dedicated credential and tiny quota. It runs manually or on a schedule, not
on every PR, and asserts only contract health—not exact time values.

## 11.6 Observability

Metrics, not payload logs:

- autocomplete requests/sessions/selections, characters-at-request, outcomes;
- provider latency and error counts by operation/status class;
- Place Details field-mask/SKU classification;
- route requests and billable elements by mode/SKU/environment;
- eligible jobs, shortlisted jobs and `NOT_EVALUATED` reasons;
- route element outcomes and commute assessment outcomes;
- fallback/circuit-open counts, quota headroom and daily user-budget exhaustion;
- canonicalisation outcomes by source/precision/confidence;
- optional-matching latency and partial-enrichment rate.

Trace with a random request/correlation ID. Do not put queries, postcodes,
coordinates, Place IDs, profile IDs, API keys or provider payloads in metric
labels, spans or logs. Alert on credential failure, sustained 429/5xx,
latency-budget breach, unexpected Pro SKU growth and cost thresholds.

# 12. Private-beta scope

## Required for beta

Feature #34:

- Written provider/legal/privacy decision and updated user notices/consent.
- `location-gateway` retained as a thin frontend edge and `location-service` as
  the sole provider-neutral domain owner, with a staged responsibility cutover.
- `google-maps-gateway` with Places API (New), secure credentials, strict field
  masks, quotas, redaction and fixtures.
- Canonical Location v2 with internal identity, precision/confidence and
  field-level provenance.
- Google discovery plus Postcodes.io UK verification/canonical persistence.
- Existing postcode/manual fallback and legacy-profile compatibility.
- Accessible, debounced, session-aware Angular autocomplete and attribution.

Feature #35:

- Drive and transit duration preferences in the existing profile.
- Fixed next-workday 08:30 Europe/London departure policy.
- Compute Route Matrix through the two new service boundaries.
- At most five eligible jobs from the current result set, batched per mode.
- Explicit remote/hybrid/onsite/unknown rules.
- Response-only advisory CommuteAssessment and explanations.
- No route cache/persistence; graceful Haversine/unavailable fallback.
- Cost metrics, user/global budgets, fixture integration and E2E tests.

## Valuable but optional for beta

- A disabled, observable commute score component for offline evaluation only;
  it must not alter production ordering until separately approved.
- Candidate-selectable morning departure time, if research shows the fixed
  policy causes material confusion.
- Refresh of Google Place IDs older than 12 months (likely unnecessary during a
  short private beta but required before long-lived use).
- An opt-in live-provider synthetic smoke test.

## Post-beta

- Walking/cycling after Google beta-mode risk, warning UX and demand validation.
- Multiple-office nearest-route evaluation and job-specific start times.
- International address models and country-specific normalisers.
- Google geocoding of incomplete job-board locations.
- Hard commute filters or production score weighting after precision/availability
  and false-negative evidence.
- Persistent route caching only with explicit written permission and deletion controls.
- Maps, route polylines, turn-by-turn detail or browser geolocation.

# 13. Implementation plan

These are proposed GitHub child Stories/Tasks. They were not created because
GitHub authentication was unavailable. “Beta blocker” means the Feature cannot
be enabled safely without it, not that unrelated beta work must stop.

## Feature #34 — Google Maps location search and normalisation

### 34.1 Provider, privacy and product approval

- Owner: `infrastructure` / product governance.
- Purpose: obtain written decision on permitted data flow, employment use,
  European personal data, retention, attribution, billing region and consent.
- Dependencies: none; begin first.
- Acceptance: signed decision matrix; approved data fields/flows; privacy/Terms
  changes; DPIA decision; stop/go criteria for Routes.
- Beta blocker: **yes**.

### 34.2 Establish `location-service` and thin `location-gateway`

- Owner: new `location-service`, `infrastructure`, existing `location-gateway`.
- Purpose: create one provider-neutral domain owner while preserving the rule
  that the frontend connects only to a thin gateway.
- Dependencies: architecture approval.
- Acceptance: repository/ownership docs; existing public v1 tests/endpoints pass;
  internal service contract; gateway contains only edge concerns; provider and
  normalisation logic removed from the gateway; deployment rollback proven.
- Beta blocker: **yes**.

### 34.3 Create `google-maps-gateway` provider boundary

- Owner: new `google-maps-gateway`, `infrastructure`.
- Purpose: isolate Places/Routes credentials, DTOs, field masks, quotas and fixtures.
- Dependencies: 34.1 decisions; can develop against fixtures alongside 34.2.
- Acceptance: internal authenticated contracts; strict field masks; no key/log
  leakage; resilience and SKU metrics; no live enablement by default.
- Beta blocker: **yes**.

### 34.4 Publish canonical Location v2 and provenance

- Owner: `location-service`; consumers in profile/job services.
- Purpose: one model for identity, precision and source confidence.
- Dependencies: 34.1, 34.2.
- Acceptance: versioned OpenAPI; ambiguity rules; persistence-safe field policy;
  compatibility examples; generated-client contract tests.
- Beta blocker: **yes**.

### 34.5 Adopt Location v2 in profile and job flows

- Owner: `user-profile-service`, `job-service`, `job-finder-gateway`.
- Purpose: persist candidate canonical origin/provenance and propagate safe job locations.
- Dependencies: 34.4.
- Acceptance: nullable migration; lazy compatibility; no Google content persisted;
  current users/search work unchanged; generated clients updated.
- Beta blocker: **yes**.

### 34.6 Deliver accessible Google-assisted location UX

- Owner: `job-seeker-copilot-client`, `location-gateway`, `location-service`.
- Purpose: recognised result selection with low request volume and robust fallback.
- Dependencies: 34.3, 34.4; UI component can begin with fixtures.
- Acceptance: debounce/minimum chars/session lifecycle; accessible keyboard/listbox;
  selected/manual states; attribution; fallback; frontend E2E.
- Beta blocker: **yes**.

### 34.7 Contract, resilience and migration validation

- Owner: cross-repository QA/infrastructure.
- Purpose: prove safe cutover and rollback.
- Dependencies: 34.2–34.6.
- Acceptance: cross-service fixture E2E; legacy user compatibility; provider-down
  scenario; cost/security dashboards; gateway-thinness architecture test.
- Beta blocker: **yes**.

## Feature #35 — Commute-time and travel-mode job matching

### 35.1 Add duration-based commute preferences

- Owner: `user-profile-service`, `job-seeker-copilot-client`.
- Purpose: drive/transit modes and maximum minutes in existing preferences.
- Dependencies: canonical origin shape from 34.4; UI/schema work can proceed in parallel.
- Acceptance: validation; partial updates/revision semantics; accessible UI;
  existing `commuteRange` retained; search propagation tests.
- Beta blocker: **yes**.

### 35.2 Add Routes Matrix adapter and commute orchestration

- Owner: `google-maps-gateway`, `location-service`.
- Purpose: bounded drive/transit estimates using the approved time policy.
- Dependencies: 34.1, 34.3, 34.4.
- Acceptance: fixtures for all element states; <=5 destinations; per-mode batch;
  time-zone/DST tests; no cache/persistence; quota/SKU metrics.
- Beta blocker: **yes**.

### 35.3 Stage and bound route candidates

- Owner: `job-service` and `job-matching-service`.
- Purpose: evaluate workplace/location validity and use current Haversine data
  before expensive routing.
- Dependencies: 34.4; can implement pure policy while 35.2 is fixture-only.
- Acceptance: remote/unknown/precision rules; deterministic top-five bound;
  not-evaluated reason; no job is removed due to route eligibility.
- Beta blocker: **yes**.

### 35.4 Calculate advisory CommuteAssessment

- Owner: `job-matching-service`.
- Purpose: compare transient estimates with preferences and emit explanation codes.
- Dependencies: 35.1–35.3.
- Acceptance: within/above boundaries; partial modes; hybrid/remote behaviour;
  no hard filter or production score change; matching failure remains optional.
- Beta blocker: **yes**.

### 35.5 Propagate and present commute explanations

- Owner: `job-service`, `job-finder-gateway`, `job-seeker-copilot-client`.
- Purpose: show understandable, attributed estimates without false precision.
- Dependencies: 35.4.
- Acceptance: versioned response overlay; approved explanation templates;
  approximate/unavailable UI; Google attribution; no saved snapshot persistence.
- Beta blocker: **yes**.

### 35.6 Cost, failure and end-to-end beta validation

- Owner: cross-repository QA/infrastructure.
- Purpose: verify provider failure cannot break job search and establish spend baseline.
- Dependencies: 35.1–35.5.
- Acceptance: representative E2E matrix; synthetic opt-in smoke if approved;
  daily/user budget tests; quota/credential/circuit alerts; measured element count
  within the design cap.
- Beta blocker: **yes**.

### Suggested execution order and parallelism

```text
34.1 approval -------------------------------> live enablement gate
34.2 location-service -----> 34.4 contract -----> 34.5 adoption ----+
34.3 Google gateway -------/          \-----> 34.6 UX --------------+-> 34.7
                                      \-----> 35.1 preferences ------+
34.3 + 34.4 -------------------------> 35.2 routes ------------------+
34.4 --------------------------------> 35.3 shortlist --------------+
35.1 + 35.2 + 35.3 -----------------> 35.4 assessment -> 35.5 -> 35.6
```

# 14. Risks and open questions

1. **Provider permission:** written confirmation is required for the precise
   Places-to-Postcodes.io flow, UK candidate-origin route requests, employment
   advisory use and duration/distance retention policy.
2. **Billing terms:** confirm the Google billing account country and whether
   global or EEA service-specific terms apply.
3. **Gateway-to-service cutover:** define the exact internal contract and remove
   the current orchestration/provider client from `location-gateway` after parity
   is proven. The gateway remains the permanent frontend edge.
4. **Origin granularity:** confirm full postcode centroid versus outcode/locality
   centroid through the DPIA and route-quality spike. Exact home addresses are
   out of scope.
5. **Job coverage:** Reed/locality-only jobs will often be ineligible for routes.
   Measure this before promising universal commute coverage; do not add Google
   bulk geocoding to beta by default.
6. **Fixed time policy:** validate 08:30 departure with beta users. A configurable
   time is optional, not required for first release.
7. **Matching ownership evolution:** ADR 0001 currently describes Application
   Tracker enrichment rather than suitability. Approve an ADR amendment making
   commute assessment a matching-owned capability while job normalisation and
   orchestration remain unchanged.
8. **GitHub planning access:** Feature/Project edits and deduplication cannot be
   completed until the GitHub app is connected or `gh` is re-authenticated.

## Product backlog and out-of-scope discoveries

No unrelated improvement was implemented. The following evidence-backed
candidates should be deduplicated and added beneath `[Epic] Product Backlog and
Continuous Improvements` once GitHub access is restored:

| Candidate | Evidence and benefit | Suggested metadata |
| --- | --- | --- |
| Add Northern Ireland coverage/fallback decision to location product policy | Postcodes.io Places covers Great Britain, leaving a known UK coverage gap. A concrete product decision avoids silently inconsistent UX. | S research / M implementation, P2, documentation/enhancement, cross-cutting, beta readiness: false for GB-limited beta. |
| Normalise workplace type for Reed and Adzuna results | Commute assessment needs `ONSITE`, `HYBRID`, `REMOTE` or a deliberately `UNKNOWN` workplace type. `JSearchJobProviderAdapter` maps an explicit remote signal, while the Reed and Adzuna adapters currently leave the new job-model default as `UNKNOWN`; consequently otherwise routable results cannot give a confident workplace interpretation. Extend only from provider-supported structured evidence, record field provenance, and add adapter contract tests. Acceptance: each supported provider has documented deterministic rules; ambiguous text remains `UNKNOWN`; remote jobs never request a route; tests cover supported and ambiguous cases. Owner: `job-service` provider adapters. Source: location-and-commute implementation. Dependencies: provider payload capabilities and terms. Benefit: more useful commute advice without guessing from free text. | M, P2, not a quick win, enhancement/data quality, job-service, beta readiness: false. Risks: provider semantics differ and unsupported inference could mislabel jobs. |
| Bring the Angular production bundle and component styles within configured budgets | The verified production build succeeds but reports a 958.04 kB initial bundle against a 500 kB budget, plus existing style-budget overruns in claimant profile, job card, job results, reporting, applications, documents and app styles. Measure contribution by route and dependency, split genuinely lazy features, remove duplicate CSS, then set evidence-based budgets rather than simply suppressing warnings. Acceptance: CI production build has no unexplained budget warning; route behaviour and accessibility tests remain green; before/after transfer sizes are recorded. Owner: `job-seeker-copilot-client`. Source: location-and-commute production-build verification. Dependencies: frontend performance baseline. Benefit: clearer regression signal and faster initial load. | M, P2, not a quick win, performance/technical debt, client, beta readiness: false. Risks: careless splitting can regress SSR or route transitions. |

Items created: **none — GitHub authentication unavailable**.  
Existing items updated: **none — GitHub authentication unavailable**.  
Quick wins identified: **none among the remaining out-of-scope candidates**.  
Blocking discoveries handled separately: **provider/privacy approval (34.1) and GitHub planning access**.  
Unrelated backlog work implemented: **none**.

# 15. Approval package

# Proposed Design for Approval

Approve Features #34 and #35 on the following basis:

1. Retain `location-gateway` as the thin, permanent frontend boundary. Add
   `location-service` as the single provider-neutral location and commute
   orchestration owner, and move the gateway's current domain/provider logic
   behind an internal service contract without changing the frontend boundary.
2. Add `google-maps-gateway` as the only Google boundary for Places API (New)
   and Routes API. Keep `postcode-io-gateway` as the UK postcode authority and
   fallback.
3. Deliver #34 first through a canonical Location v2 with JSC identity,
   provider references, precision/confidence and field-level provenance.
   Persist only approved non-Google/user/provider canonical fields and Google
   Place ID; keep other Google Places content transient.
4. Require provider/legal/privacy approval, consent/notice updates, secure
   server credentials, quotas and attribution before live Google enablement.
5. Deliver #35 on that model with drive and transit only, a next-workday 08:30
   Europe/London departure, at most five eligible destinations per result-set
   evaluation, and no route-result cache or persistence.
6. Treat commute as an estimated advisory assessment for onsite/hybrid work.
   Remote is not routed; unknown/approximate/unavailable remains visible and is
   never treated as unsuitable. Do not hard-filter or alter production scoring
   in the beta.
7. Preserve existing Postcodes.io/manual location flows, Haversine distance and
   core job results whenever Google or matching is unavailable.
8. Implement only through the ordered Stories in section 13, with fixture-based
   normal CI and a separately governed synthetic live smoke test if approved.

Approval phrase: **Approved — implement this design.**

Until that explicit approval is given, no implementation work should start.
