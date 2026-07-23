# Contributing

Use a short-lived branch from `develop`, keep service source changes in the
owning service repository, and submit infrastructure changes through review.

Before review:

1. Run `python3 -m unittest discover -s tests`.
2. Run `python3 -m compileall -q scripts`.
3. Run `mvn -B -Dcheckstyle.skip=true -f build-tools/pom.xml validate`.
4. Validate the affected Compose profiles with example-only configuration.
5. Document operational, compatibility, security, and rollback implications.

Never commit actual `.env` files, generated clients, service JARs, service
source trees, provider data, user data, recordings, or build output.

The inherited build-tools quality executions are not yet a standalone
repository gate because their rule files are not packaged for parent-POM
consumers. Do not represent the model-validation command above as a completed
quality scan; publication and enforcement are tracked in the Infrastructure
epic.
