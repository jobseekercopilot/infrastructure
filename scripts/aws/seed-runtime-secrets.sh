#!/usr/bin/env bash
set -euo pipefail

environment_name=${1:-public-beta}
region=${AWS_REGION:-eu-west-2}
prefix="jsc-${environment_name}"

if [[ "$environment_name" != "public-beta" || "$region" != "eu-west-2" ]]; then
  echo "Refusing to seed outside public-beta/eu-west-2." >&2
  exit 2
fi

for command_name in aws jq openssl mktemp; do
  command -v "$command_name" >/dev/null || {
    echo "Missing required command: $command_name" >&2
    exit 2
  }
done

secret_has_value() {
  aws secretsmanager list-secret-version-ids \
    --region "$region" \
    --secret-id "$1" \
    --query 'length(Versions[?contains(VersionStages, `AWSCURRENT`)])' \
    --output text | grep -qx '1'
}

put_json_secret() {
  secret_id="$1"
  json_file="$2"
  aws secretsmanager put-secret-value \
    --region "$region" \
    --secret-id "$secret_id" \
    --secret-string "file://$json_file" \
    --query VersionId \
    --output text >/dev/null
}

secure_tmp="$(mktemp -d)"
chmod 0700 "$secure_tmp"
cleanup() {
  find "$secure_tmp" -type f -exec sh -c 'command -v shred >/dev/null && shred -u "$1" || rm -f "$1"' _ {} \;
  rmdir "$secure_tmp" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

token_keys=(
  AUTH_SERVICE_TOKEN ENVIRONMENT_DATA_TOKEN
  APPLICATION_TRACKER_PRODUCER_TOKEN APPLICATION_TRACKER_READER_TOKEN
  REPORTING_GATEWAY_SERVICE_TOKEN DOCUMENT_STORE_PRODUCER_TOKEN
  DOCUMENT_STORE_READER_TOKEN DOCUMENT_STORE_RETENTION_ADMIN_TOKEN
  DOCUMENT_STORE_ERASURE_FINGERPRINT_KEY
  DOCUMENT_EXPORT_GATEWAY_TOKEN CV_COVER_LETTER_GATEWAY_TOKEN
  CV_COVER_LETTER_TO_PAYMENT_SERVICE_TOKEN REJECTED_GENERATION_OPERATOR_TOKEN
  DOCUMENT_GENERATION_GATEWAY_TO_PAYMENT_SERVICE_TOKEN BFF_TO_PAYMENT_GATEWAY_TOKEN
  PAYMENT_GATEWAY_TO_PAYMENT_SERVICE_TOKEN PAYMENT_GATEWAY_TO_STRIPE_GATEWAY_TOKEN
  STRIPE_GATEWAY_TO_PAYMENT_SERVICE_TOKEN ACCOUNT_LIFECYCLE_TO_PAYMENT_SERVICE_TOKEN
  PAYMENT_SERVICE_TO_STRIPE_GATEWAY_LIFECYCLE_TOKEN LOCATION_SERVICE_TOKEN
  GOOGLE_MAPS_GATEWAY_TOKEN
)

merge_file_key() {
  local key=$1
  local value_file=$2
  local next="$secure_tmp/core.next.json"
  jq --arg key "$key" --rawfile value "$value_file" '.[$key] = $value' \
    "$secure_tmp/core.json" > "$next"
  mv "$next" "$secure_tmp/core.json"
  core_changed=true
}

ensure_random_key() {
  local key=$1
  local bytes=$2
  if jq -e --arg key "$key" 'has($key)' "$secure_tmp/core.json" >/dev/null; then
    jq -e --arg key "$key" '.[$key] | type == "string" and length >= 32' \
      "$secure_tmp/core.json" >/dev/null || {
        echo "Refusing invalid existing core secret field: $key" >&2
        exit 3
      }
    return
  fi
  openssl rand -base64 "$bytes" | tr -d '\n' > "$secure_tmp/$key"
  merge_file_key "$key" "$secure_tmp/$key"
}

core_secret="$prefix/runtime/core"
core_changed=false
if secret_has_value "$core_secret"; then
  aws secretsmanager get-secret-value \
    --region "$region" \
    --secret-id "$core_secret" \
    --query SecretString \
    --output text > "$secure_tmp/core.json"
  jq -e 'type == "object"' "$secure_tmp/core.json" >/dev/null || {
    echo "Refusing invalid existing JSON secret: $core_secret" >&2
    exit 3
  }
else
  printf '{}\n' > "$secure_tmp/core.json"
fi
chmod 0600 "$secure_tmp/core.json"

private_present=false
public_present=false
jq -e 'has("JWT_PRIVATE_KEY_BASE64")' "$secure_tmp/core.json" >/dev/null && private_present=true
jq -e 'has("JWT_PUBLIC_KEY_BASE64")' "$secure_tmp/core.json" >/dev/null && public_present=true
if [[ "$private_present" != "$public_present" ]]; then
  echo "Refusing a partial existing JWT key pair in $core_secret" >&2
  exit 3
fi
if [[ "$private_present" == true ]]; then
  for key in JWT_PRIVATE_KEY_BASE64 JWT_PUBLIC_KEY_BASE64; do
    jq -e --arg key "$key" '.[$key] | type == "string" and length >= 128' \
      "$secure_tmp/core.json" >/dev/null || {
        echo "Refusing invalid existing core secret field: $key" >&2
        exit 3
      }
  done
else
  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$secure_tmp/jwt-private.pem" 2>/dev/null
  openssl pkey -in "$secure_tmp/jwt-private.pem" -pubout -out "$secure_tmp/jwt-public.pem" 2>/dev/null
  base64 -w0 "$secure_tmp/jwt-private.pem" > "$secure_tmp/jwt-private.b64"
  base64 -w0 "$secure_tmp/jwt-public.pem" > "$secure_tmp/jwt-public.b64"
  merge_file_key JWT_PRIVATE_KEY_BASE64 "$secure_tmp/jwt-private.b64"
  merge_file_key JWT_PUBLIC_KEY_BASE64 "$secure_tmp/jwt-public.b64"
fi

for key in "${token_keys[@]}"; do
  ensure_random_key "$key" 48
done
ensure_random_key REJECTED_GENERATION_QUARANTINE_KEY_BASE64 32

if jq -e 'has("DOCUMENT_STORE_ERASURE_FINGERPRINT_PREVIOUS_KEYS")' "$secure_tmp/core.json" >/dev/null; then
  jq -e '.DOCUMENT_STORE_ERASURE_FINGERPRINT_PREVIOUS_KEYS | type == "string" and length <= 4103' \
    "$secure_tmp/core.json" >/dev/null || {
      echo "Refusing invalid previous Document Store erasure fingerprint key ring" >&2
      exit 3
    }
else
  next="$secure_tmp/core.next.json"
  jq '.DOCUMENT_STORE_ERASURE_FINGERPRINT_PREVIOUS_KEYS = ""' "$secure_tmp/core.json" > "$next"
  mv "$next" "$secure_tmp/core.json"
  core_changed=true
fi

chmod 0600 "$secure_tmp/core.json"
if [[ "$core_changed" == true ]]; then
  put_json_secret "$core_secret" "$secure_tmp/core.json"
  echo "Reconciled missing fields without rotating existing values: $core_secret"
else
  echo "Validated existing complete secret: $core_secret"
fi

database_entries=(
  'authentication:authentication'
  'user_profile:user_profile'
  'job_service:job_service'
  'document_generation:document_generation'
  'document_store:document_store'
  'application_tracker:application_tracker'
  'payment:payment'
)

for entry in "${database_entries[@]}"; do
  IFS=: read -r database username <<< "$entry"
  secret_id="$prefix/database/$database"
  if secret_has_value "$secret_id"; then
    aws secretsmanager get-secret-value \
      --region "$region" \
      --secret-id "$secret_id" \
      --query SecretString \
      --output text > "$secure_tmp/$database.existing.json"
    jq -e \
      --arg database "$database" \
      --arg username "$username" \
      'type == "object" and .database == $database and .username == $username and (.password | type == "string" and length >= 32)' \
      "$secure_tmp/$database.existing.json" >/dev/null || {
        echo "Refusing invalid existing database secret schema: $secret_id" >&2
        exit 3
      }
    echo "Validated existing database secret: $secret_id"
    continue
  fi
  password_file="$secure_tmp/$database.password"
  openssl rand -base64 48 | tr -d '\n' > "$password_file"
  jq -n \
    --arg database "$database" \
    --arg username "$username" \
    --rawfile password "$password_file" \
    '{database:$database,username:$username,password:$password}' \
    > "$secure_tmp/$database.json"
  chmod 0600 "$secure_tmp/$database.json"
  put_json_secret "$secret_id" "$secure_tmp/$database.json"
  echo "Seeded secret: $secret_id"
done

echo "Runtime secret seeding complete. No existing values were rotated."
