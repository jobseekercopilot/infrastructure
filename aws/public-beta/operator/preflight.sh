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

echo "release preflight complete"
