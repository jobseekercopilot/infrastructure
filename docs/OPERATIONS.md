# Operations

## Safe first run

1. Authenticate `gh` for the private `jobseekercopilot` organisation.
2. Run `python3 scripts/workspace/doctor.py`.
3. Review `python3 scripts/workspace/bootstrap.py`.
4. Run the same command with `--apply` to clone missing repositories.
5. Copy the required `.env.*.example`; keep real values untracked.
6. Validate Compose before build or start.

The bootstrap refuses unexpected existing directories and never pulls or
switches an existing checkout.

## Profiles

- `e2e`: deterministic fixture-only validation; no real external activity.
- `data-acquisition`: controlled fixture capture; review provider, privacy, and
  retention rules before use.
- `live`: real-provider integration. Use approved credentials and explicit
  operational ownership.

## Recovery

Stop the selected Compose project using the stack scripts before changing
profiles. Preserve named-volume data before destructive database changes. If a
credential appears in source, logs, screenshots, or build artifacts, rotate it
and record the response privately.

Current Compose definitions and operational scripts were extracted from the
legacy root and require the Infrastructure epic’s clean-room validation before
they are treated as production-ready.
