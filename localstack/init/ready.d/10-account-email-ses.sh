#!/bin/sh
set -eu

sender="accounts@jobseekercopilot.com"
configuration_set="JobSeekerCopilotAccountEmails"

attempt=0
until awslocal ses list-identities >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 30 ]; then
    echo "Account-email LocalStack initialisation failed: SES did not become ready." >&2
    exit 1
  fi
  sleep 1
done

awslocal ses verify-email-identity --email-address "$sender" >/dev/null

existing_configuration_set="$(
  awslocal ses list-configuration-sets \
    --query "ConfigurationSets[?Name=='${configuration_set}'].Name" \
    --output text
)"
if [ "$existing_configuration_set" != "$configuration_set" ]; then
  awslocal ses create-configuration-set \
    --configuration-set "Name=${configuration_set}" >/dev/null
fi

verification_status="$(
  awslocal ses get-identity-verification-attributes \
    --identities "$sender" \
    --query "VerificationAttributes.\"${sender}\".VerificationStatus" \
    --output text
)"
if [ "$verification_status" != "Success" ]; then
  echo "Account-email LocalStack initialisation failed: sender identity is unavailable." >&2
  exit 1
fi

configured="$(
  awslocal ses list-configuration-sets \
    --query "ConfigurationSets[?Name=='${configuration_set}'].Name" \
    --output text
)"
if [ "$configured" != "$configuration_set" ]; then
  echo "Account-email LocalStack initialisation failed: configuration set is unavailable." >&2
  exit 1
fi

echo "Account-email LocalStack SES is ready: sender identity and configuration set confirmed."
