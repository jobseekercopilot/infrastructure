# Changing the platform

## Find the owner first

Use [data ownership](../data/ownership.md) and the [service catalogue](../services/catalogue.md). A gateway change should not silently take ownership from a domain service, and a consumer must not query another service's schema.

## Normal change flow

```text
feature branch
  → repository tests and contract checks
  → pull request into develop
  → reviewed Infrastructure contract/workspace lock update when needed
  → main only during a release
```

Do not commit directly to `main`, rewrite unrelated history, or mix architecture cleanup into a focused change.

## If the API changes

1. Update the producer implementation and its OpenAPI snapshot.
2. Run semantic-drift and compatibility checks in the producer.
3. Update each consumer's revision/checksum pin.
4. Regenerate clients using the repository script; never edit generated source.
5. Update `infrastructure/config/contracts-lock.json` and workspace lock when the fleet moves.
6. Update journey/architecture docs if behaviour or ownership changed.

## If persistent data changes

- Add a forward-only Flyway migration in the owning service.
- Keep production schema validation enabled; do not rely on Hibernate auto-creation.
- Document backup/restore, retention, privacy, and rollout impact where relevant.
- Update the ownership table and domain ER diagram if a major entity/boundary changed.

## If a cross-service workflow changes

Review identity propagation, idempotency, deadlines, partial failure, durable recovery, and observability. Update the sequence diagram and call/dependency map. A new cross-service write must not report success before its owner can establish the durable outcome.

## Testing levels

| Level | Owner |
|---|---|
| Unit/component | Individual repository |
| API semantic drift/compatibility | Producer and pinned consumers |
| Database migration/restart/backup | Persistent service |
| Container/non-root/health | Individual repository |
| Compose/profile/mode isolation | Infrastructure |
| Browser journey/accessibility | E2E plus client component tests |

Use fixture mode for deterministic tests. Live acquisition is a separate, explicitly approved operator workflow and is never normal CI.

