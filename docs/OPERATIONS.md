# Operations

## Safe first run

1. Authenticate `gh` for the private `jobseekercopilot` account.
2. Run `python3 scripts/workspace/doctor.py`.
3. Review `python3 scripts/workspace/bootstrap.py`.
4. Run the same command with `--apply` to clone missing repositories.
5. Generate the selected ignored environment with
   `scripts/security/generate_profile_env.py`; never populate tracked examples.
6. Validate Compose before build or start.

The bootstrap refuses unexpected existing directories and never pulls or
switches an existing checkout.

## Profiles

- `e2e`: deterministic fixture-only validation; no real external activity.
- `data-acquisition`: controlled fixture capture; review provider, privacy, and
  retention rules before use.
- `live`: real-provider integration. Use approved credentials and explicit
  operational ownership. This remains a local live-provider profile and is not
  production deployment evidence.

The document path's current identity matrix, local PostgreSQL/object-storage
boundary, validation commands, rotation procedure and production gaps are in
[`RUNTIME_ENVIRONMENTS.md`](RUNTIME_ENVIRONMENTS.md).

## Recovery

Stop the selected Compose project using the stack scripts before changing
profiles. Preserve named-volume data before destructive database changes. If a
credential appears in source, logs, screenshots, or build artifacts, rotate it
and record the response privately.

Current Compose definitions and operational scripts were extracted from the
legacy root and require the Infrastructure epic’s clean-room validation before
they are treated as production-ready.

## Private Maven package credentials

Producer workflows publish their own package with a repository
`GITHUB_TOKEN`. A different private repository cannot use its own
`GITHUB_TOKEN` to read that repository-scoped Maven package.

Cross-repository consumers use a dedicated classic token named
`JSC_PACKAGE_READ_TOKEN` with `read:packages` and `repo`. Store it only as an
Actions secret or an untracked local environment value. Maven settings refer to
`${env.JSC_PACKAGE_READ_TOKEN}`; they never contain the credential itself.
Container builds receive the settings file through a BuildKit secret.

Do not reuse an interactive `gh` token, a publication token, a build argument,
an image environment variable or a tracked settings file. Rotate the consumer
token on a documented schedule and immediately after any suspected exposure.
