# Authentication account-email delivery

Password-reset and password-changed messages are owned by Authentication
Service. They do not use the waitlist, contact, landing-page Lambda, or their
message purposes.

## Runtime modes

Local development and automated tests must use:

```text
AUTH_ACCOUNT_EMAIL_DELIVERY_MODE=fixture
```

A hosted Authentication Service may use SES only after the CloudFormation stack
in `aws/account-email-ses.yaml` is deployed and its managed policy is attached
to that service's runtime role:

```text
AUTH_ACCOUNT_EMAIL_DELIVERY_MODE=ses
AUTH_ACCOUNT_EMAIL_APPLICATION_BASE_URL=https://app.jobseekercopilot.com
AUTH_ACCOUNT_EMAIL_SENDER=accounts@jobseekercopilot.com
AUTH_ACCOUNT_EMAIL_SUPPORT_URL=https://jobseekercopilot.com/contact
AUTH_ACCOUNT_EMAIL_SES_REGION=eu-west-2
AUTH_ACCOUNT_EMAIL_SES_CONFIGURATION_SET=JobSeekerCopilotAccountEmails
```

AWS credentials use the SDK default credential chain and remain in the hosted
backend runtime. Do not put them in browser configuration or tracked files.

## Readiness checks

Before enabling SES mode:

1. Deploy `aws/account-email-ses.yaml` in the Authentication Service account and
   region.
2. Confirm the `jobseekercopilot.com` SES identity remains verified with valid
   DKIM.
3. Attach the output managed-policy ARN only to the Authentication Service
   runtime role.
4. Subscribe an operational destination to the encrypted SNS topic and confirm
   bounce, complaint, reject, delivery-delay, send, and delivery events.
5. Confirm account-level suppression remains enabled.
6. Send one controlled password-reset message to an approved tester and verify
   the configuration set and `message-purpose` tag in SES delivery events.

The application always names the configuration set explicitly. The policy
allows `ses:SendEmail` only from `accounts@jobseekercopilot.com` and scopes the
request to the verified domain identity and dedicated configuration-set ARN.
