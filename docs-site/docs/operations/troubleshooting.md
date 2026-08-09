# Troubleshooting

## Fleet-first sequence

Run the existing diagnostics in this order:

```bash
python3 scripts/doctor.py
./scripts/validate-workspace.sh
./scripts/status.sh --profile basic-fixture
./scripts/logs.sh --profile basic-fixture
```

Use the same profile that started the stack.

## Common symptoms

| Symptom | Check | Meaning |
|---|---|---|
| Client returns `503` for auth/profile | UMG and Authentication/Profile health; BFF gateway URL | Dependency unavailable |
| Client returns `504` | BFF/downstream timeout and service logs | Validated request deadline expired |
| Job search is `PARTIAL` | `providerResults` and `matchingStatus` | At least one provider or matching enrichment degraded |
| Job search returns unavailable | Provider-mode endpoints and System Data health | No enabled provider succeeded |
| `FEATURE_NOT_AVAILABLE` under payment | Expected on `develop` | BFF payment boundary is disabled |
| Location has no results | Query validation, Location/Postcode health, fixture dataset | Empty can be valid; provider failures use distinct statuses |
| Generation remains pending | Read operation state and correlation ID; inspect Doc Gen logs | Durable coordinator is waiting/recovering a step |
| Document download fails | Exact file/artifact ID, owner session, Store/object status | Metadata and bytes are separately validated |
| Reporting timeline lacks document events | Document Store health/log warning | Reporting tolerates Store activity failure |
| Startup names a missing variable | Generated profile environment/schema | Fail-closed configuration; never log the value |

## Repository locks and dirty work

Workspace update scripts will not switch branches or fast-forward a dirty repository. Commit, stash, or move that work deliberately; do not delete it to satisfy tooling. Contract mismatch errors require updating the producer snapshot and consumer pin together.

## Provider mode

For Reed, Adzuna, JSearch, Postcode.io, LLM, and Stripe, distinguish fixture failures from live credentials. Never add a real key to a fixture profile to “test” a failure. Use the reviewed overlay and provider-mode endpoint.

## Logs and sensitive data

Use correlation IDs, operation IDs, provider names, and stable error categories. Do not copy cookies, bearer tokens, service tokens, prompts, generated documents, profile content, or rejected provider bodies into issues or documentation.
