#!/bin/sh
set -eu

if [ -z "${SERVICE_ENDPOINTS:-}" ]; then
  echo "release preflight refused: SERVICE_ENDPOINTS is empty" >&2
  exit 2
fi

old_ifs="$IFS"
IFS=','
for endpoint in $SERVICE_ENDPOINTS; do
  IFS="$old_ifs"
  case "$endpoint" in
    http://*.public-beta.internal:*) ;;
    *)
      echo "release preflight refused: endpoint outside the private namespace" >&2
      exit 2
      ;;
  esac

  response_file="$(mktemp)"
  trap 'rm -f "$response_file"' EXIT HUP INT TERM
  if ! curl --fail --silent --show-error \
      --connect-timeout 3 --max-time 15 \
      --output "$response_file" "$endpoint"; then
    echo "release preflight failed: $endpoint" >&2
    exit 3
  fi

  case "$endpoint" in
    */actuator/health)
      if ! jq -e '.status == "UP"' "$response_file" >/dev/null; then
        echo "release preflight unhealthy: $endpoint" >&2
        exit 3
      fi
      ;;
  esac
  rm -f "$response_file"
  trap - EXIT HUP INT TERM
  echo "release preflight healthy: $endpoint"
  IFS=','
done
IFS="$old_ifs"

case "${EXPECTED_CHECKOUT_AVAILABLE:-}" in
  true|false) ;;
  *) echo "release preflight refused: invalid checkout expectation" >&2; exit 2 ;;
esac
if [ -z "${PAYMENT_READINESS_ENDPOINT:-}" ] || [ -z "${BFF_TO_PAYMENT_GATEWAY_TOKEN:-}" ]; then
  echo "release preflight refused: payment readiness contract is incomplete" >&2
  exit 2
fi
case "$PAYMENT_READINESS_ENDPOINT" in
  http://payment-gateway.public-beta.internal:8098/api/v2/payments/checkout-readiness) ;;
  *) echo "release preflight refused: invalid payment readiness endpoint" >&2; exit 2 ;;
esac

payment_response="$(mktemp)"
trap 'rm -f "$payment_response"' EXIT HUP INT TERM
if ! curl --fail --silent --show-error \
    --connect-timeout 3 --max-time 15 \
    --header "X-Service-Token: $BFF_TO_PAYMENT_GATEWAY_TOKEN" \
    --header "X-Payment-Owner: release-preflight" \
    --output "$payment_response" "$PAYMENT_READINESS_ENDPOINT"; then
  echo "release preflight failed: payment checkout-readiness unavailable" >&2
  exit 3
fi
if [ "$EXPECTED_CHECKOUT_AVAILABLE" = true ]; then
  jq -e '
    .checkoutAvailable == true and .code == "READY" and
    .paymentServiceCode == "READY" and .providerCode == "READY" and
    .mode == "LIVE"
  ' "$payment_response" >/dev/null || {
    echo "release preflight failed: live checkout is not READY" >&2
    exit 3
  }
else
  jq -e '.checkoutAvailable == false' "$payment_response" >/dev/null || {
    echo "release preflight failed: checkout unexpectedly available while disabled" >&2
    exit 3
  }
fi
rm -f "$payment_response"
trap - EXIT HUP INT TERM
echo "release preflight payment checkout-readiness matched the reviewed mode"

if [ -z "${DOCUMENT_ERASURE_READINESS_ENDPOINT:-}" ] \
    || [ -z "${DOCUMENT_STORE_RETENTION_ADMIN_TOKEN:-}" ] \
    || [ -z "${DOCUMENT_ERASURE_RETENTION_POLICY_VERSION:-}" ] \
    || [ -z "${DOCUMENT_ERASURE_BACKUP_POLICY_VERSION:-}" ]; then
  echo "release preflight refused: document-erasure readiness contract is incomplete" >&2
  exit 2
fi
case "$DOCUMENT_ERASURE_READINESS_ENDPOINT" in
  http://document-store-service.public-beta.internal:8089/internal/retention/v1/permanent-erasures/readiness) ;;
  *) echo "release preflight refused: invalid document-erasure readiness endpoint" >&2; exit 2 ;;
esac
case "${DOCUMENT_ERASURE_MAXIMUM_BACKUP_RETENTION_DAYS:-}" in
  35) ;;
  *) echo "release preflight refused: document-erasure backup retention must be exactly 35 days" >&2; exit 2 ;;
esac

document_erasure_response="$(mktemp)"
trap 'rm -f "$document_erasure_response"' EXIT HUP INT TERM
if ! curl --fail --silent --show-error \
    --connect-timeout 3 --max-time 15 \
    --header "X-Service-Token: $DOCUMENT_STORE_RETENTION_ADMIN_TOKEN" \
    --output "$document_erasure_response" "$DOCUMENT_ERASURE_READINESS_ENDPOINT"; then
  echo "release preflight failed: document-erasure readiness unavailable" >&2
  exit 3
fi
jq -e \
  --arg retention "$DOCUMENT_ERASURE_RETENTION_POLICY_VERSION" \
  --arg backup "$DOCUMENT_ERASURE_BACKUP_POLICY_VERSION" '
    .schemaVersion == "document-permanent-erasure-readiness.v3" and
    .enabled == true and .ready == true and .status == "READY" and
    .policyVersion == $retention and
    .backupRetentionPolicyVersion == $backup and
    .recoveryDays == 35 and
    .maximumBackupRetentionDays == 35 and
    .backupExpiryEvidenceRequired == true and
    .recoveryJournalWritePending == 0 and
    .recoveryJournalEvidenceMissing == 0 and
    .liveErasureReconciliationPending == 0 and
    .restoreJournalReadPending == 0 and
    .restoreReplayPending == 0 and
    (.backupRetentionPending | type == "number") and
    .backupRetentionPending >= 0 and
    .backupRetentionOverdue == 0
  ' "$document_erasure_response" >/dev/null || {
    echo "release preflight failed: document-erasure capability is not READY" >&2
    exit 3
  }
rm -f "$document_erasure_response"
trap - EXIT HUP INT TERM
echo "release preflight document-erasure readiness matched the reviewed policy"

echo "release preflight complete"
