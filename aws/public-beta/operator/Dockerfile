ARG POSTGRES_IMAGE
FROM ${POSTGRES_IMAGE}

ARG RDS_CA_BUNDLE_URL
ARG RDS_CA_BUNDLE_SHA256

RUN apk add --no-cache aws-cli ca-certificates curl jq

RUN test -n "${RDS_CA_BUNDLE_URL}" \
    && test -n "${RDS_CA_BUNDLE_SHA256}" \
    && mkdir -p /etc/jsc/rds \
    && curl --fail --show-error --silent --location "${RDS_CA_BUNDLE_URL}" -o /tmp/rds-global-bundle.pem \
    && echo "${RDS_CA_BUNDLE_SHA256}  /tmp/rds-global-bundle.pem" | sha256sum -c - \
    && cp /tmp/rds-global-bundle.pem /etc/jsc/rds/global-bundle.pem \
    && chmod 0444 /etc/jsc/rds/global-bundle.pem \
    && rm /tmp/rds-global-bundle.pem

COPY bootstrap-databases.sh /opt/jsc/bootstrap-databases.sh
COPY clone-restored-document-store.sh /opt/jsc/clone-restored-document-store.sh
COPY prepare-restore-source-canary.sh /opt/jsc/prepare-restore-source-canary.sh
COPY preflight.sh /opt/jsc/preflight.sh
COPY verify-restored-semantics.sh /opt/jsc/verify-restored-semantics.sh
COPY verify-migrations.sh /opt/jsc/verify-migrations.sh

RUN chmod 0555 /opt/jsc/bootstrap-databases.sh /opt/jsc/clone-restored-document-store.sh \
    /opt/jsc/prepare-restore-source-canary.sh /opt/jsc/preflight.sh \
    /opt/jsc/verify-migrations.sh /opt/jsc/verify-restored-semantics.sh

USER 65534:65534
ENTRYPOINT ["/bin/sh"]
