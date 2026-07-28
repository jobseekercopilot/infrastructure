# Authentication account-email delivery

**Production SES resources: CODE-READY — NOT DEPLOYED.**

Password-reset and password-changed messages are owned by Authentication
Service. They do not use the waitlist, contact, landing-page Lambda, or their
message purposes.

Both `local-ses` and hosted `ses` use the same production adapter:
AWS SDK for Java 2.x module `software.amazon.awssdk:ses`,
`software.amazon.awssdk.services.ses.SesClient`, and the SES 2010-12-01
`SendEmail` service API. No AWS SDK for Java 1.x or SMTP adapter is used.

## Runtime modes

| Environment | Email mode | Destination |
| --- | --- | --- |
| Unit/component tests | `fixture` | In-memory/captured fixture |
| Local full stack | `local-ses` | LocalStack SES |
| Hosted beta | `ses` | Real AWS SES |
| Production | `ses` | Real AWS SES |

The normal `full-fixture` profile remains deterministic:

```text
AUTH_ACCOUNT_EMAIL_DELIVERY_MODE=fixture
```

`full-local-ses` retains the fixture-backed application but routes account
email through the production SES adapter to the pinned, SES-only LocalStack
container:

```text
AUTH_ACCOUNT_EMAIL_DELIVERY_MODE=local-ses
AUTH_ACCOUNT_EMAIL_SES_ENDPOINT=http://localstack:4566
AUTH_ACCOUNT_EMAIL_SES_REGION=eu-west-2
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test
```

The dummy values are required and are not secrets. The LocalStack gateway is
published only on `127.0.0.1:4566`. Authentication reaches it only over the
internal Compose network; LocalStack also joins the loopback-bound bridge so
the local test harness can use `/_aws/ses`. AWS endpoint forwarding, certificate
download and usage events are disabled. Sent messages are ephemeral local test
data and can be cleared with `DELETE http://127.0.0.1:4566/_aws/ses`.

LocalStack Community captures sender, destination, subject, text and HTML
content. Its `/_aws/ses` store does not expose configuration-set or message-tag
fields, so those request fields are verified at the adapter boundary and remain
part of the same SES v1 `SendEmail` call.

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

## LocalStack validation boundary

LocalStack proves SES API compatibility, dedicated sender/configuration
selection, local message capture and the application reset journey. It does
not prove real IAM role attachment, SES domain or DKIM status, SPF or DMARC,
mailbox delivery, AWS suppression-list behaviour, actual bounce/complaint
delivery, encrypted SNS delivery events, or production configuration-set event
publication. LocalStack state and captured messages are never persisted or
committed.

One hosted validation remains deferred: deploy the real SES resources, attach
the Authentication Service role, send one controlled reset, confirm real
delivery and configuration-set tagging, and verify delivery-event handling.

## Readiness checks

These checks are for that later hosted validation; they are not performed by
the local profile.

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
allows `ses:SendEmail` only through SES API version `2010-12-01`, only from
`accounts@jobseekercopilot.com`, and scopes the request to the verified domain
identity and dedicated configuration-set ARN.
