# Google Maps activation and data handling

Google Maps is an optional, fail-closed provider for UK location selection and
commute estimates. The only approved external APIs are Places API (New) and
Routes API. Maps JavaScript API, Geocoding API, legacy Directions and legacy
Distance Matrix are not part of this runtime.

## Isolation and purpose

```text
Angular -> location-gateway -> location-service -> google-maps-gateway -> Google
                                         \-----> postcode-io-gateway
```

Only `google-maps-gateway` receives the Google credential or calls Google. A
request can contain the typed location query, selected Place ID, Postcodes.io
origin/destination centroids, travel mode, departure time and bounded route
options. Names, email addresses, CVs, employment history, application data and
generated documents must never be included.

## Persistence decision

| Data | Classification | Retention |
| --- | --- | --- |
| User commute preferences | First-party user data | Profile lifecycle |
| JSC location ID and location type/precision | Application-owned canonical data | Profile lifecycle |
| Postcode, display name and centroid from Postcodes.io | Non-Google canonical data with explicit provenance | Profile lifecycle |
| Google Place ID | Google identifier | May be stored; refresh if reused after 12 months |
| Google autocomplete text and address components | Google Maps content | Active request/session display only; never database, event, analytics or log storage |
| Google Places coordinates, formatted addresses, names and types | Unneeded Google Maps content | Not requested by Place Details |
| Routes duration, distance and provider response | Google Maps content | Response-only; removed from saved-job snapshots and never stored in profiles, events, analytics or logs |

`user-profile-service` rejects canonical fields whose declared source is
`GOOGLE_PLACES`. A Google-selected location is resolved through Postcodes.io;
the persisted canonical values retain `POSTCODES_IO` provenance and only the
Google Place ID crosses as a provider reference.

## User transparency

Autocomplete suggestions and Google-backed commute estimates display
`Google Maps` attribution in the same visual container. The Angular application
publishes `/privacy` and `/terms`, links them from every page, describes the
bounded Google data flow and links to Google's Terms and Privacy Policy. This is
an implemented technical notice, not a claim of legal compliance.

## Secure local activation

Normal development and CI use `GOOGLE_MAPS_ENABLED=false`. The dedicated
`google-maps-smoke` profile enables Google Maps while all other external
providers remain fixture-backed. The owner-authorised `real-providers` manual
environment also enables this overlay alongside its live job, postcode and LLM
adapters; deterministic fixture and E2E profiles remain unchanged.

The API key belongs in the owner-only workspace file:

```text
<workspace>/config/.secrets.env
```

with mode `0600` and this name (value omitted):

```dotenv
GOOGLE_MAPS_API_KEY=
```

Validate without printing the value:

```bash
python3 scripts/security/provider_secrets.py --providers GOOGLE --check-repositories
```

Start and verify only after the GCP checklist below passes:

```bash
./scripts/start-local.sh --profile google-maps-smoke --build
./scripts/health-check.sh --profile google-maps-smoke
./scripts/status.sh --profile google-maps-smoke
```

The Compose overlay mounts the key only at
`/run/secrets/GOOGLE_MAPS_API_KEY` in `google-maps-gateway`; it is not a container
environment variable and is not mounted into the client or any other service.

Return to the provider-disabled baseline with:

```bash
./scripts/stop-local.sh --profile google-maps-smoke
./scripts/start-local.sh --profile full-fixture
```

## GCP activation checklist

Before live traffic, record evidence without credential values:

1. Dedicated Job Seeker Copilot project and intended billing-account link.
2. Only `places-backend.googleapis.com` (Places API New) and
   `routes.googleapis.com` enabled for the feature.
3. A dedicated server key restricted to those two APIs and the smoke host's
   current egress IP. Production must use a separate key restricted to its
   stable egress IP; never relax it for local development.
4. Conservative per-method quotas for autocomplete, place details and route
   matrix elements, low enough to bound accidental loops while allowing the
   handful of smoke requests.
5. A low monthly billing budget with threshold notifications. A budget is an
   alert, not a spending cap; quotas are the cost-limiting control.
6. Metrics checked immediately after the smoke test for API, credential,
   consumer and request-count consistency.

If billing, restriction or quota evidence is missing, keep Google disabled.

## Attribution and policy sources

- [Places API policies](https://developers.google.com/maps/documentation/places/web-service/policies)
- [Routes API policies](https://developers.google.com/maps/documentation/routes/policies)
- [Google Maps Platform Terms](https://cloud.google.com/maps-platform/terms)
- [Google Maps Platform Service Specific Terms](https://cloud.google.com/maps-platform/terms/maps-service-terms)
