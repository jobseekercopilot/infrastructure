# External integrations

## Integration matrix

| System | Purpose | Boundary | Default local behaviour | Credentials |
|---|---|---|---|---|
| Reed | Job search/detail | Reed Gateway | System Data fixture | `REED_API_KEY` in live overlay (secret) |
| Adzuna | Job search | Adzuna Gateway | Fixture; independently enabled | `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` (secret) |
| JSearch/RapidAPI | Job search | JSearch Gateway | Fixture; independently enabled | `JSEARCH_API_KEY` (secret) |
| Postcodes.io | UK place/postcode | Postcode.io Gateway | Fixture in base stack; public live API supported by gateway | No standard API secret |
| OpenAI | LLM generation | LLM Gateway | Fixture model response | `OPENAI_API_KEY` in `real-providers` (secret) |
| Stripe | Checkout/webhook | Stripe Gateway | Fixture; browser payment blocked | Live secret/webhook keys not allowed in standard profiles |
| AWS SES | Account email | Authentication Service adapter | Fixture, or LocalStack in `full-local-ses` | AWS runtime identity in hosted deployment |
| AWS landing services | Waitlist/contact | Landing repository | Separate from authenticated app stack | Deployment-specific AWS configuration |
| ClamAV | Untrusted document scan | Document Store | Local container, signature-updated | None |
| LocalStack | Local SES emulation | Infrastructure overlay | Optional ephemeral local container | Local-only fixed test configuration |

## Safe mode selection

Provider mode is selected by Infrastructure, not a browser query parameter. Standard fixture/E2E profiles reject live provider secret names. Live profiles fail when required values are missing and keep credentials in an ignored, owner-only workspace file.

Never put secrets in:

- Angular environment files or bundles;
- repository `.env.example` files;
- Dockerfiles/images;
- generated OpenAPI clients;
- documentation or screenshots.

## Optional and unavailable integrations

Google Maps commute routing is not implemented on `develop`. NHS Jobs is also a skeleton. They have no current environment variables, Compose services, or callable runtime contracts in the source of truth.
