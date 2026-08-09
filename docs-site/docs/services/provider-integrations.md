# Provider integrations

| Gateway | Live provider | Fixture source | Key responsibility | Live status |
|---|---|---|---|---|
| Reed Gateway | Reed API | System Data | Search/detail request and canonical provider mapping | Optional overlay |
| Adzuna Gateway | Adzuna API | System Data | Credentialed search, paging bounds, mapping | Optional overlay |
| JSearch Gateway | JSearch via RapidAPI | System Data | Country/language/paging bounds, mapping | Optional overlay |
| Postcode.io Gateway | Postcodes.io | System Data | Place and postcode/outcode lookup | Public live API supported; fixture default |
| LLM Gateway | OpenAI | System Data | Typed generation, response bounds, usage/model evidence | Optional `real-providers` overlay |
| Stripe Gateway | Stripe | System Data | Checkout session and signed webhook handling | Not enabled by standard profiles |

Provider credentials remain in server-side secret files/environment and never reach Angular. Fixture profiles explicitly forbid live credentials. Gateways expose `/internal/provider-mode` where implemented so verification can prove the selected mode.

## System Data Service

System Data owns versioned, synthetic, non-production datasets. Provider gateways call its fixture API. E2E/operator flows can request named states; System Data then calls each domain's guarded reset/seed/verify API. Those routes require explicit non-production profile controls and distinct secrets.

It does not own production job search, user, application, document, or payment state and does not access another database directly.

## AWS

The main runtime uses AWS SES for production account email when configured. Local `full-local-ses` runs the same adapter against ephemeral LocalStack. The separate landing repository uses AWS-backed waitlist/contact infrastructure. Infrastructure also contains AWS deployment material, but local Compose remains free and self-contained.

## Not runtime services

`google-maps-gateway`, `location-service`, and `nhs-jobs-gateway` have no application source, Dockerfile, port, or catalogue entry on `develop`. They must not be shown as active dependencies. See [location status](../journeys/location.md).

