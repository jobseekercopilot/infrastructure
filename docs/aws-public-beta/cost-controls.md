# Public-beta AWS cost controls

The planning baseline is approximately **USD 560/month** in `eu-west-2` before
credits and before material traffic growth. Re-price it in the AWS Pricing
Calculator immediately before launch; this is an engineering estimate, not a
quote.

These hosting costs are not the customer-price catalog. For public-beta release
planning, the dated 11 August subscription hypotheses and the later
£7.99/£16.99/£34.99 pack values are historical and superseded by non-renewing
document-credit packs: 10/£4.99, 25/£11.99 and 60/£19.99, with two free credits.
Measured AI and payment-fee sensitivity for this decision is recorded in the
landing repository's `docs/launch/pricing-decision-2026-08-22.md`. Checkout is
implemented but remains
release-gated/disabled and no live charge is claimed by this plan.

| Cost group | Planning range/month | Main variance |
|---|---:|---|
| one `m7i.2xlarge`, 100 GiB gp3 | $340–390 | hours and London price |
| `db.t4g.medium`, 50 GiB gp3, backups/PI | $80–115 | storage, I/O, retained backups |
| one NAT Gateway and ALB | $55–85 | processed GB and LCUs |
| WAF, Route 53, KMS, S3, ECR, logs, SES | $45–85 | requests, logs, scans, document volume |
| expected planning total | **about $560** | traffic and retained data |

The retained bootstrap budget structure owns the **USD 750 alert ceiling**;
Terraform must consume the identical `MonthlyAlertBudgetUsd` output as
`foundation_monthly_alert_budget_usd` and `monthly_budget_usd`. It is not a
hard cap. Actual-spend notifications are sent at USD 350, 500, 560, 650, 700
and 750. Forecast notifications use the same six levels. The split across
three AWS Budget resources is intentional because AWS limits one budget to
five notifications. A Cost Anomaly Detection subscription triggers from a
USD 20 absolute impact and reuses an existing account-wide AWS-services
monitor when one already exists.

All budget, anomaly, backup and operational messages publish through the
encrypted operations topic. Its owner email subscription must be confirmed
before activation. Cost-allocation tags may take time to activate, so the
billing console must confirm that `CostCentre=public-beta` is an active
cost-allocation tag before relying on the filtered budgets.

Harder engineering bounds are separate:

- lean ASG min/desired/max are all one; ECS managed capacity cannot add a
  second node, and its `0/100` host refresh cannot add temporary capacity;
- the bootstrap Apply policy also caps ASG create/update at one node and pins
  a numeric launch-template version; HA requires a separately reviewed
  bootstrap/IAM and cost-ceiling change before Terraform can request it;
- lean service maximum is one and deployment is stop-first;
- RDS maximum storage is 200 GiB and backup retention is 35 days;
- one reviewed `securityLogRetentionDays` value applies to both CloudWatch and
  access-log S3 retention (30 days in the lean baseline);
- external providers need manifest request and cost ceilings;
- Google remains disabled without a named GCP project, exact billable quota IDs
  and daily limits, a true external verification record, separate GCP alerts at
  50/75/90/100%, and an owned emergency-disable runbook; and
- public traffic can be stopped by returning the ALB to fixed `503`, then
  scaling application services to zero through the protected release path.

AWS Budgets does not automatically stop resources. An operator must respond to
alerts using the incident/maintenance steps in the deployment runbook. A change
to HA, instance shape, NAT count, retention, WAF rules or traffic assumptions
requires an updated calculator export and a newly approved alert ceiling.

Google Maps is a specialist API outside AWS hosting costs. Google documents its
startup-program Maps benefit as a **separate application**, so no expected
benefit is included in the AWS estimate and Maps stays disabled until the
separate application, quota and billing controls are approved.
GCP budget alerts are also notification controls rather than a hard cap; the
exact service quotas and protected disable switch are the enforcement path.

The approved $1,000 AWS Activate award covers about 1.8 months of the expected
$560 lean baseline before traffic growth. It is a temporary runway subsidy, not
a recurring discount in the post-credit cost model. Pricing must be reviewed
when the award approaches exhaustion and after 30/90 days of observed use.

## Cost-reduction decision before launch

The fixed compute host is the clearest near-term saving that does not weaken
the private-network, backup or single-node safety boundaries. AWS's public
Price List API for Linux shared-tenancy On-Demand instances in `eu-west-2`,
retrieved on 22 August 2026, gives the following 730-hour comparisons:

| Candidate | vCPU / memory | Hourly | 730-hour compute | Change from current |
|---|---:|---:|---:|---:|
| current `m7i.2xlarge` | 8 / 32 GiB | $0.46620 | $340.33 | baseline |
| `m7i-flex.2xlarge` | 8 / 32 GiB | $0.44288 | $323.30 | save $17.02/month |
| recommended benchmark: `m6a.2xlarge` | 8 / 32 GiB | $0.39960 | $291.71 | save $48.62/month |
| deeper cost benchmark: `r6a.xlarge` | 4 / 32 GiB | $0.26640 | $194.47 | save $145.85/month |
| later multi-architecture option: `m7g.2xlarge` | 8 / 32 GiB | $0.37740 | $275.50 | save $64.82/month |

Moving to `m6a.2xlarge` would reduce the planning total from about $560 to
about **$511/month**, before traffic, and extend $1,000 of credits from about
1.79 to **1.96 months**. It retains x86-64 and the measured 8-vCPU/32-GiB
capacity envelope. It must not be selected until the exact protected image set
passes the current 1/5/10/15/20/25-user browser ladder, all image health checks,
the 29-task placement proof and a fresh AWS Calculator review. A failed or
materially slower benchmark keeps `m7i.2xlarge`.

The more meaningful `r6a.xlarge` target would reduce the planning total to
about **$414/month** and extend $1,000 of credits to about **2.41 months** while
retaining 32 GiB. It also halves compute to four vCPU. Current placement
reserves 4,736 CPU units for application services plus 1,792 for ClamAV, the
release operator and host/ECS headroom, so it cannot place safely without a
reviewed reservation rebudget. Treat it as a separate benchmark: lower soft CPU
reservations only where measured utilisation supports it, preserve burst
behaviour, repeat the complete concurrency ladder, and reject the candidate if
the 15-user comfortable point or timeout headroom materially regresses.

`m7g.2xlarge` saves only a further $16.21/month over `m6a.2xlarge`, while
requiring a reviewed ARM64/multi-architecture build and runtime proof across
all production images and ClamAV. That is not a sensible pre-launch trade.

The stack already uses the free S3 gateway endpoint, so S3 traffic avoids NAT
Gateway hourly and processing charges. The remaining NAT Gateway carries
required third-party HTTPS traffic and AWS services without a cost-effective
gateway endpoint. Replacing it with a self-managed NAT instance would add
patching, failover and throughput responsibility to the only production node;
it is not recommended for this beta. Interface endpoints should be introduced
only when measured NAT bytes exceed the endpoints' combined hourly and data
cost. The shared `db.t4g.medium` is already a burstable Graviton database for
seven logical databases; do not halve it to 2 GiB without observed connection,
free-memory, swap and restore-load evidence.

Therefore the immediate recommendation is: keep the checked-in safe baseline,
benchmark `r6a.xlarge` as the meaningful cost-down target and
`m6a.2xlarge` as the same-capacity fallback, and switch only with the evidence
above. Reaching materially beyond 2.4 months from the $1,000 award would require
a larger architectural change to the 27-service fixed footprint, not a safe
last-minute infrastructure toggle.
