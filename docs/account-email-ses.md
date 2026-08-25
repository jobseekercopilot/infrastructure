# Authentication account-email delivery

**Release status: infrastructure-owned path implemented; live read-only checks
and one owner-approved delivery remain required.**

Password-reset and password-changed messages are owned by Authentication
Service. They do not use the waitlist/contact Lambdas, their configuration set,
or their message purposes.

## Ownership

| Resource or decision | Owner |
| --- | --- |
| `jobseekercopilot.com` SES identity and Easy DKIM records | Landing email stack |
| Retained encrypted `jsc-public-beta-operations` topic and notification KMS key | Manual public-beta bootstrap |
| `JobSeekerCopilotAccountEmails` configuration set and `account-email-events` destination | Public-beta Terraform |
| `accounts@jobseekercopilot.com` runtime sender and password-reset content | Authentication Service |
| Authentication task-role send grant | Public-beta Terraform, capped by the bootstrap workload boundary |
| Controlled tester mailbox and receipt confirmation | Named release owner; never Terraform or CI |

The former standalone `aws/account-email-ses.yaml` template was never part of
the protected release workflow and is removed. There is now one owner for each
resource. Terraform must not create, import, update or delete the landing-owned
domain identity/DKIM records. The landing stack must not create the application
configuration set.

## Runtime and authorization contract

Both `local-ses` and hosted `ses` use AWS SDK for Java 2.x
`software.amazon.awssdk.services.ses.SesClient` and its `SendEmail` operation.
Hosted credentials come only from the ECS task-role chain.
The role and its permissions boundary allow only:

- `ses:SendEmail` (never raw or bulk email);
- the verified `jobseekercopilot.com` identity and exact
  `JobSeekerCopilotAccountEmails` configuration set;
- the exact `accounts@jobseekercopilot.com` From address;
- secure transport.

The send grant deliberately does not add a `ses:ApiVersion` condition. AWS's
IAM condition uses SES API-generation values rather than the SDK service-model
date, and binding it to `2010-12-01` denied the hosted request before SES could
accept it. The exact action, identity, configuration set, From address and
secure-transport constraints retain the intended least-privilege boundary.

The inline grant is attached only when `enabled_integrations.account_email` is
true. Creating the configuration/event resources does not attach credentials,
start tasks, expose the listener or send an email.

The application always supplies the configuration-set name and exactly one
`message-purpose` tag (`password-reset` or `password-changed`) in the same
`SendEmail` request. It never uses open/click tracking. The event destination
publishes send, reject, hard-bounce, complaint, delivery and delivery-delay
events to the retained operations topic. Account and configuration-set
suppression both cover `BOUNCE` and `COMPLAINT`.

AWS requires SES to have explicit publish permission on the SNS topic and KMS
usage permission when that topic uses a customer-managed key. The bootstrap
policies scope both permissions to the exact account and configuration-set ARN:

- [SES SNS notification permissions](https://docs.aws.amazon.com/ses/latest/dg/configure-sns-notifications.html)
- [SNS KMS publisher permissions](https://docs.aws.amazon.com/sns/latest/dg/sns-key-management.html)

## Local validation boundary

The deterministic `full-fixture` and E2E profiles force:

```text
AUTH_ACCOUNT_EMAIL_DELIVERY_MODE=fixture
```

`full-local-ses` uses the production adapter against SES-only, loopback-bound,
ephemeral LocalStack:

```text
AUTH_ACCOUNT_EMAIL_DELIVERY_MODE=local-ses
AUTH_ACCOUNT_EMAIL_SES_ENDPOINT=http://localstack:4566
AUTH_ACCOUNT_EMAIL_SES_REGION=eu-west-2
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test
```

These exact dummy credentials are local-only. Hosted `ses` mode rejects an
endpoint override and rejects the dummy values. LocalStack proves adapter,
configuration-set, purpose-tag and reset-journey behavior; it does not prove a
live identity, DKIM, IAM attachment, SNS/KMS publication or mailbox delivery.

## Protected release order

1. Promote this infrastructure change through `develop` and protected `main`.
2. Update the retained bootstrap stack from that exact `main` revision. This
   adds read/manage permissions for the exact configuration set and the exact
   SES publisher statements to the operations topic and notification key.
3. Run the protected `foundation` action with zero application tasks and the
   listener fixed at `503`. Terraform creates the configuration set and event
   destination and attaches no send policy unless account email is approved.
4. The release script runs `verify_account_email_ses.py`. It reads SES, SNS and
   KMS state and fails unless production access, sending, enforcement, domain
   verification, DKIM, suppression, event types, encryption and exact source
   policies all match. The operations topic must have exactly one confirmed
   email subscription; the verifier never prints its endpoint. The verifier
   cannot send email.
5. Build and prepare the immutable private fleet. The same read-only verifier
   runs again before tasks start and immediately before activation.
6. A named owner approves one tester account/mailbox they control. Trigger one
   ordinary password-reset request through the real application path, then
   confirm mailbox delivery plus the configuration set and
   `message-purpose=password-reset` event. Do not retain the recipient address,
   reset URL/token, subject or body in release evidence.

The controlled delivery is deliberately not automated. Record only a redacted
evidence reference, UTC time, release ID, configuration-set name, purpose tag
and delivery outcome. The exact remaining human input is the approved tester
account/mailbox; the confirmed operations subscription must not be assumed to
be that tester account without the owner's approval.

## Hosted environment

```text
AUTH_ACCOUNT_EMAIL_DELIVERY_MODE=ses
AUTH_ACCOUNT_EMAIL_APPLICATION_BASE_URL=https://app.jobseekercopilot.com
AUTH_ACCOUNT_EMAIL_SENDER=accounts@jobseekercopilot.com
AUTH_ACCOUNT_EMAIL_SUPPORT_URL=https://jobseekercopilot.com/contact
AUTH_ACCOUNT_EMAIL_SES_REGION=eu-west-2
AUTH_ACCOUNT_EMAIL_SES_CONFIGURATION_SET=JobSeekerCopilotAccountEmails
```

AWS credentials and password-reset material must never enter browser
configuration, Terraform inputs, approval manifests, logs or tracked files.
